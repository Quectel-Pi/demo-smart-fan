// fan_vision - lightweight UVC + RKNN person detector for the smart-fan demo.
//
// It emits one JSON object per inference. The Python controller consumes that
// stream and owns all appliance state. A small JPEG snapshot is also written so
// the local web UI can show what the camera currently sees.

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "infer/jpeg_io.h"
#include "infer/preprocess.h"
#include "infer/rknn_engine.h"
#include "infer/types.h"
#include "infer/yolo_post.h"
#include "video/v4l2_source.h"

namespace {

using Clock = std::chrono::steady_clock;
std::atomic<bool> g_running{true};

void on_signal(int) { g_running.store(false); }

struct Options {
    std::string model = "/userdata/smart-fan/models/yolov8s-640-640.rknn";
    std::string device = "/dev/video73";
    std::string snapshot = "/userdata/smart-fan/state/current.jpg";
    int width = 640;
    int height = 480;
    int fps = 30;
    int infer_fps = 10;
    int core_mask = 0;
    float conf = 0.45f;
    float nms = 0.45f;
    double snapshot_fps = 2.0;
    double min_height_ratio = 0.15;
    double min_aspect = 0.55;
    bool no_rga = false;
};

void usage(const char* argv0) {
    std::printf(
        "Usage: %s [options]\n"
        "  --model PATH       RKNN model (default /userdata/smart-fan/models/yolov8s-640-640.rknn)\n"
        "  --device PATH      V4L2 device (default /dev/video73)\n"
        "  --width N          Capture width (default 640)\n"
        "  --height N         Capture height (default 480)\n"
        "  --fps N            Capture FPS (default 30)\n"
        "  --infer-fps N      Person inference FPS (default 10)\n"
        "  --conf F           Person confidence (default 0.45)\n"
        "  --nms F            NMS IoU threshold (default 0.45)\n"
        "  --core N           RKNN core mask (default 0 = auto)\n"
        "  --snapshot PATH    Atomically updated JPEG snapshot; empty disables\n"
        "  --snapshot-fps F   Snapshot rate (default 2)\n"
        "  --min-height F     Minimum person height / image height (default 0.15)\n"
        "  --min-aspect F     Minimum person height / width (default 0.55)\n"
        "  --no-rga           Disable RGA preprocessing\n",
        argv0);
}

bool arg_value(int argc, char** argv, int* i, const char* name, const char** out) {
    if (*i + 1 >= argc) {
        std::fprintf(stderr, "missing value for %s\n", name);
        return false;
    }
    *out = argv[++*i];
    return true;
}

bool parse_options(int argc, char** argv, Options* o) {
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        const char* v = nullptr;
        if (a == "-h" || a == "--help") {
            usage(argv[0]);
            std::exit(0);
        } else if (a == "--model") {
            if (!arg_value(argc, argv, &i, "--model", &v)) return false;
            o->model = v;
        } else if (a == "--device") {
            if (!arg_value(argc, argv, &i, "--device", &v)) return false;
            o->device = v;
        } else if (a == "--width") {
            if (!arg_value(argc, argv, &i, "--width", &v)) return false;
            o->width = std::atoi(v);
        } else if (a == "--height") {
            if (!arg_value(argc, argv, &i, "--height", &v)) return false;
            o->height = std::atoi(v);
        } else if (a == "--fps") {
            if (!arg_value(argc, argv, &i, "--fps", &v)) return false;
            o->fps = std::atoi(v);
        } else if (a == "--infer-fps") {
            if (!arg_value(argc, argv, &i, "--infer-fps", &v)) return false;
            o->infer_fps = std::atoi(v);
        } else if (a == "--conf") {
            if (!arg_value(argc, argv, &i, "--conf", &v)) return false;
            o->conf = (float)std::atof(v);
        } else if (a == "--nms") {
            if (!arg_value(argc, argv, &i, "--nms", &v)) return false;
            o->nms = (float)std::atof(v);
        } else if (a == "--core") {
            if (!arg_value(argc, argv, &i, "--core", &v)) return false;
            o->core_mask = std::atoi(v);
        } else if (a == "--snapshot") {
            if (!arg_value(argc, argv, &i, "--snapshot", &v)) return false;
            o->snapshot = v;
        } else if (a == "--snapshot-fps") {
            if (!arg_value(argc, argv, &i, "--snapshot-fps", &v)) return false;
            o->snapshot_fps = std::atof(v);
        } else if (a == "--min-height") {
            if (!arg_value(argc, argv, &i, "--min-height", &v)) return false;
            o->min_height_ratio = std::atof(v);
        } else if (a == "--min-aspect") {
            if (!arg_value(argc, argv, &i, "--min-aspect", &v)) return false;
            o->min_aspect = std::atof(v);
        } else if (a == "--no-rga") {
            o->no_rga = true;
        } else {
            std::fprintf(stderr, "unknown argument: %s\n", a.c_str());
            return false;
        }
    }
    return o->width > 0 && o->height > 0 && o->fps > 0 && o->infer_fps > 0;
}

bool atomic_jpeg_write(const std::string& path, const mb::ImageRGB& img, std::string* err) {
    if (path.empty()) return true;
    std::vector<uint8_t> jpg;
    if (!mb::jpeg_encode_mem(img, 82, &jpg, err)) return false;
    const std::string tmp = path + ".tmp";
    FILE* f = std::fopen(tmp.c_str(), "wb");
    if (!f) {
        if (err) *err = "open snapshot temp failed: " + tmp;
        return false;
    }
    const bool ok = std::fwrite(jpg.data(), 1, jpg.size(), f) == jpg.size();
    const bool closed = std::fclose(f) == 0;
    if (!ok || !closed || std::rename(tmp.c_str(), path.c_str()) != 0) {
        std::remove(tmp.c_str());
        if (err) *err = "write snapshot failed: " + path;
        return false;
    }
    return true;
}

uint64_t now_ms() {
    return (uint64_t)std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

void print_people(const std::vector<mb::Detection>& people, int image_w, int image_h, int frame,
                  double ai_ms, int infer_fps) {
    const mb::Detection* best = nullptr;
    for (const mb::Detection& d : people) {
        if (!best || (d.x2 - d.x1) * (d.y2 - d.y1) >
                         (best->x2 - best->x1) * (best->y2 - best->y1)) {
            best = &d;
        }
    }

    std::printf(
        "{\"ts_ms\":%llu,\"frame\":%d,\"width\":%d,\"height\":%d,"
        "\"valid\":%s,\"count\":%zu,\"infer_fps\":%d,\"ai_ms\":%.2f",
        (unsigned long long)now_ms(), frame, image_w, image_h, best ? "true" : "false",
        people.size(), infer_fps, ai_ms);
    if (best) {
        const float cx = (best->x1 + best->x2) * 0.5f / (float)image_w;
        const float cy = (best->y1 + best->y2) * 0.5f / (float)image_h;
        std::printf(
            ",\"person\":{\"cx\":%.5f,\"cy\":%.5f,\"x1\":%.2f,\"y1\":%.2f,"
            "\"x2\":%.2f,\"y2\":%.2f,\"score\":%.4f}",
            cx, cy, best->x1, best->y1, best->x2, best->y2, best->score);
    }
    std::printf(",\"people\":[");
    const size_t shown = std::min<size_t>(people.size(), 8);
    for (size_t i = 0; i < shown; ++i) {
        const mb::Detection& d = people[i];
        if (i) std::printf(",");
        std::printf("{\"cx\":%.5f,\"cy\":%.5f,\"x1\":%.2f,\"y1\":%.2f,"
                    "\"x2\":%.2f,\"y2\":%.2f,\"score\":%.4f}",
                    (d.x1 + d.x2) * 0.5f / (float)image_w,
                    (d.y1 + d.y2) * 0.5f / (float)image_h, d.x1, d.y1, d.x2, d.y2,
                    d.score);
    }
    std::printf("]}\n");
    std::fflush(stdout);
}

}  // namespace

int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IOLBF, 0);
    Options opt;
    if (!parse_options(argc, argv, &opt)) {
        usage(argv[0]);
        return 2;
    }

    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);
    std::signal(SIGPIPE, SIG_IGN);

    std::string err;
    mb::RknnEngine engine;
    if (!engine.load(opt.model, opt.core_mask, &err)) {
        std::fprintf(stderr, "model load failed: %s\n", err.c_str());
        return 1;
    }
    engine.print_versions();
    if (engine.input_channel() != 3 || engine.input_count() != 1) {
        std::fprintf(stderr, "unsupported model: expected one 3-channel image input\n");
        return 1;
    }

    mb::V4l2Source camera;
    camera.set_hardware_jpeg(true);
    if (!camera.open(opt.device, opt.width, opt.height, opt.fps, "MJPG", 4, &err)) {
        std::fprintf(stderr, "camera open failed: %s\n", err.c_str());
        return 1;
    }

    mb::ImageRGB model_input;
    model_input.width = engine.input_width();
    model_input.height = engine.input_height();
    mb::PreprocessOptions prep;
    prep.use_rga = !opt.no_rga;

    mb::YoloParams yp;
    yp.conf_threshold = opt.conf;
    yp.nms_threshold = opt.nms;

    int frame = 0;
    Clock::time_point next_infer = Clock::now();
    Clock::time_point next_snapshot = Clock::now();
    const auto infer_interval =
        std::chrono::microseconds((int64_t)(1000000.0 / std::max(1, opt.infer_fps)));
    const auto snapshot_interval = opt.snapshot_fps > 0
                                       ? std::chrono::microseconds(
                                             (int64_t)(1000000.0 / opt.snapshot_fps))
                                       : std::chrono::microseconds(0);

    std::fprintf(stderr, "fan_vision ready: %s %dx%d@%d, model %dx%d, infer %dfps\n",
                 camera.device().c_str(), camera.width(), camera.height(), opt.fps,
                 model_input.width, model_input.height, opt.infer_fps);

    while (g_running.load()) {
        mb::VideoFrame vf;
        if (!camera.read(&vf, 1000, &err)) {
            if (!err.empty()) {
                std::fprintf(stderr, "camera read failed: %s\n", err.c_str());
                std::this_thread::sleep_for(std::chrono::milliseconds(250));
            }
            continue;
        }

        mb::ImageRGB image;
        if (!camera.decode_frame(vf, &image, &err)) {
            std::fprintf(stderr, "frame decode failed: %s\n", err.c_str());
            continue;
        }
        ++frame;

        const auto now = Clock::now();
        if (opt.snapshot_fps > 0 && now >= next_snapshot) {
            std::string snap_err;
            if (!atomic_jpeg_write(opt.snapshot, image, &snap_err) && !snap_err.empty()) {
                std::fprintf(stderr, "%s\n", snap_err.c_str());
            }
            while (next_snapshot <= now) next_snapshot += snapshot_interval;
        }

        if (now < next_infer) continue;
        next_infer = now + infer_interval;

        mb::Letterbox lb;
        const char* warn = nullptr;
        if (!mb::letterbox_rgb(image, &model_input, &lb, prep, &warn)) {
            std::fprintf(stderr, "preprocess failed\n");
            continue;
        }
        if (warn) {
            std::fprintf(stderr, "%s\n", warn);
            warn = nullptr;
        }

        const auto t0 = Clock::now();
        if (!engine.run(model_input.data.data(), model_input.size_bytes(), &err)) {
            std::fprintf(stderr, "inference failed: %s\n", err.c_str());
            continue;
        }
        std::vector<mb::Detection> dets;
        if (!mb::yolo_postprocess(engine, yp, lb, &dets, &err)) {
            std::fprintf(stderr, "postprocess failed: %s\n", err.c_str());
            continue;
        }
        std::vector<mb::Detection> people;
        for (const mb::Detection& d : dets) {
            if (d.cls_id != 0) continue;
            const float w = std::max(1.0f, d.x2 - d.x1);
            const float h = std::max(1.0f, d.y2 - d.y1);
            if (h / (float)image.height < opt.min_height_ratio) continue;
            if (h / w < opt.min_aspect) continue;
            people.push_back(d);
        }
        const double ai_ms =
            std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
        print_people(people, image.width, image.height, frame, ai_ms, opt.infer_fps);
    }

    camera.close();
    engine.release();
    return 0;
}
