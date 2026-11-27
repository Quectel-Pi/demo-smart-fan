from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

LOG = logging.getLogger(__name__)

INDEX_HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#edf5f3">
<title>轻风 · 智能风扇</title>
<style>
:root{color-scheme:light;--bg:#edf5f3;--surface:rgba(255,255,255,.82);--surface-solid:#fff;--ink:#17343b;--muted:#688088;--line:rgba(33,82,91,.13);--accent:#137c88;--accent-deep:#0c5e69;--mint:#2a9d8f;--sky:#79c7d2;--coral:#d56b58;--amber:#c58a34;--shadow:0 18px 50px rgba(34,76,82,.10)}
*{box-sizing:border-box}html{min-width:320px}body{margin:0;min-height:100vh;color:var(--ink);font:15px/1.5 Inter,"PingFang SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;background:radial-gradient(circle at 8% 0%,rgba(121,199,210,.34),transparent 30rem),radial-gradient(circle at 94% 12%,rgba(42,157,143,.16),transparent 26rem),linear-gradient(160deg,#f8fbfa 0%,var(--bg) 52%,#e8f1ef 100%);background-attachment:fixed}
body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.38;background-image:linear-gradient(rgba(19,124,136,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(19,124,136,.045) 1px,transparent 1px);background-size:44px 44px;mask-image:linear-gradient(to bottom,#000,transparent 72%)}
main{position:relative;max-width:1240px;margin:0 auto;padding:28px 24px 52px}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:24px}.top-actions{display:flex;align-items:center;gap:10px}.lang-switch{display:inline-flex;align-items:center;padding:3px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.7);box-shadow:0 8px 24px rgba(33,82,91,.06)}.lang-switch button{min-width:42px;padding:5px 9px;border:0;border-radius:999px;background:transparent;box-shadow:none;color:var(--muted);font-size:11px}.lang-switch button:hover{transform:none;background:transparent;color:var(--accent)}.lang-switch button.active{background:var(--accent);color:#fff;box-shadow:0 3px 9px rgba(19,124,136,.22)}
.brand{display:flex;align-items:center;gap:14px}.brand-mark{display:grid;place-items:center;width:52px;height:52px;border-radius:17px;background:linear-gradient(145deg,#178a96,#0d6673);color:#fff;box-shadow:0 10px 24px rgba(13,102,115,.22)}.brand-mark svg{width:30px;height:30px}.eyebrow{margin:0 0 2px;color:var(--accent);font-size:10px;font-weight:800;letter-spacing:.18em}.brand h1{margin:0;font-size:clamp(24px,3vw,32px);line-height:1.12;letter-spacing:-.035em}.brand .sub{margin:6px 0 0;color:var(--muted);font-size:13px}
.health{display:inline-flex;align-items:center;gap:8px;padding:9px 13px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.7);box-shadow:0 8px 24px rgba(33,82,91,.06);color:var(--muted);font-size:13px;font-weight:650;white-space:nowrap}.health i{width:8px;height:8px;border-radius:50%;background:var(--amber);box-shadow:0 0 0 4px rgba(197,138,52,.12)}.health.online i{background:var(--mint);box-shadow:0 0 0 4px rgba(42,157,143,.14)}.health.offline i{background:var(--coral);box-shadow:0 0 0 4px rgba(213,107,88,.13)}
.dashboard{display:grid;grid-template-columns:minmax(0,1.52fr) minmax(340px,.78fr);gap:20px;align-items:start}.panel{border:1px solid rgba(255,255,255,.72);border-radius:24px;background:var(--surface);box-shadow:var(--shadow);backdrop-filter:blur(16px)}
.camera-panel{padding:16px}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:3px 3px 14px}.panel-head h2{margin:0;font-size:17px;letter-spacing:-.01em}.panel-head p{margin:3px 0 0;color:var(--muted);font-size:12px}.live-chip{display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border-radius:999px;background:#f5faf9;border:1px solid var(--line);color:var(--muted);font-size:11px;font-weight:700}.live-chip i{width:6px;height:6px;border-radius:50%;background:#9aabae}.live-chip.on{color:var(--accent-deep);background:#ecf8f6}.live-chip.on i{background:var(--mint);animation:pulse 1.8s infinite}
.preview{position:relative;overflow:hidden;isolation:isolate;border-radius:18px;background:#071b22;aspect-ratio:4/3;box-shadow:inset 0 0 0 1px rgba(255,255,255,.08)}#snapshot{display:block;width:100%;height:100%;object-fit:contain;background:#071b22}.preview:after{content:"";position:absolute;inset:auto 0 0;height:22%;z-index:1;pointer-events:none;background:linear-gradient(transparent,rgba(4,20,27,.55))}#overlay{position:absolute;inset:0;z-index:3;pointer-events:none}.person-box{position:absolute;border:2px solid #71e0d2;border-radius:7px;box-shadow:0 0 0 1px rgba(9,55,60,.3),0 0 24px rgba(113,224,210,.35)}.person-box:after{content:attr(data-label);position:absolute;left:-2px;top:-24px;padding:3px 7px;border-radius:5px;background:#71e0d2;color:#08353a;font-size:10px;font-weight:800;letter-spacing:.02em}.camera-empty{position:absolute;inset:0;z-index:2;display:grid;place-items:center;padding:24px;text-align:center;color:#c4d3d5;background:radial-gradient(circle at 50% 35%,rgba(61,119,127,.26),transparent 38%),#071b22}.camera-empty.hidden{display:none}.camera-empty svg{width:52px;height:52px;margin-bottom:10px;opacity:.62}.camera-empty strong{display:block;color:#e2efef;font-size:15px}.camera-empty span{display:block;margin-top:5px;font-size:12px;color:#8fa7ab}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin-top:12px}.metric{min-width:0;padding:13px;border-radius:15px;background:rgba(247,251,250,.92);border:1px solid var(--line)}.metric span{display:block;margin-bottom:5px;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.06em}.metric strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:16px;letter-spacing:-.02em}.metric strong.ok{color:var(--mint)}.metric strong.hot{color:var(--accent)}.metric strong.warn{color:var(--amber)}.metric strong.off{color:#849396}
.controls{padding:20px}.control-title{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:18px}.control-title h2{margin:0;font-size:22px;letter-spacing:-.035em}.control-title p{margin:4px 0 0;color:var(--muted);font-size:12px}.state-pill{max-width:145px;padding:7px 10px;border-radius:10px;background:#edf8f6;color:var(--accent-deep);font-size:11px;font-weight:750;text-align:center}
.section-label{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:20px 0 9px}.section-label:first-of-type{margin-top:0}.section-label h3{margin:0;font-size:12px;letter-spacing:.02em}.section-label span{color:var(--muted);font-size:10px}
.power-grid,.gear-grid,.follow-grid,.timer-grid{display:grid;gap:8px}.power-grid{grid-template-columns:1fr 1fr}.gear-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.follow-grid{grid-template-columns:1fr 1fr}.timer-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
button{appearance:none;border:1px solid var(--line);border-radius:13px;background:rgba(255,255,255,.82);color:var(--ink);padding:12px 10px;font:inherit;font-size:13px;font-weight:700;cursor:pointer;box-shadow:0 3px 10px rgba(33,82,91,.035);transition:transform .16s ease,background .16s ease,border-color .16s ease,box-shadow .16s ease}button:hover{transform:translateY(-1px);border-color:rgba(19,124,136,.38);box-shadow:0 8px 18px rgba(33,82,91,.08)}button:active{transform:translateY(0)}button:focus-visible{outline:3px solid rgba(19,124,136,.22);outline-offset:2px}button.primary{border-color:transparent;background:linear-gradient(145deg,#168894,#0d6975);color:#fff;box-shadow:0 10px 20px rgba(13,105,117,.19)}button.primary:hover{box-shadow:0 13px 24px rgba(13,105,117,.24)}button.danger{border-color:rgba(213,107,88,.2);background:#fff6f3;color:#a74d3e}button.active{border-color:transparent;background:linear-gradient(145deg,#24a292,#147984);color:#fff;box-shadow:0 9px 18px rgba(20,121,132,.2)}button.danger.active{background:linear-gradient(145deg,#dd4f43,#bd4038);box-shadow:0 9px 18px rgba(189,64,56,.2)}.timer-cancel{grid-template-columns:1fr}.gear-grid button{display:flex;flex-direction:column;align-items:center;gap:1px;padding:10px 5px}.gear-grid b{font-size:13px}.gear-grid small{color:var(--muted);font-size:9px;font-weight:600}.gear-grid button.active b,.gear-grid button.active small{color:#fff}.gear-grid button.active{background:linear-gradient(155deg,#178a96,#0c6672);box-shadow:0 8px 18px rgba(12,102,114,.19)}
.setting-card{margin-top:20px;padding:14px;border:1px solid var(--line);border-radius:16px;background:rgba(247,251,250,.9)}.setting-row{display:flex;align-items:center;justify-content:space-between;gap:16px}.setting-copy strong{display:block;font-size:13px}.setting-copy span{display:block;margin-top:4px;color:var(--muted);font-size:11px}.setting-copy small{display:block;margin-top:3px;color:#8a9b9e;font-size:9px}.switch{position:relative;flex:0 0 auto;display:inline-flex;width:48px;height:28px;cursor:pointer}.switch input{position:absolute;width:1px;height:1px;opacity:0}.switch-track{width:100%;height:100%;border-radius:999px;background:#c8d3d3;box-shadow:inset 0 0 0 1px rgba(16,58,65,.08);transition:.2s ease}.switch-track:after{content:"";position:absolute;top:4px;left:4px;width:20px;height:20px;border-radius:50%;background:#fff;box-shadow:0 2px 6px rgba(18,54,61,.22);transition:.2s ease}.switch input:checked+.switch-track{background:linear-gradient(90deg,#26a596,#137c88)}.switch input:checked+.switch-track:after{transform:translateX(20px)}.switch input:focus-visible+.switch-track{outline:3px solid rgba(19,124,136,.22);outline-offset:3px}.switch input:disabled+.switch-track{opacity:.55;cursor:wait}
.detail-list{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:16px}.detail{padding:10px 11px;border-radius:12px;background:rgba(255,255,255,.62);border:1px solid rgba(33,82,91,.09)}.detail span{display:block;color:var(--muted);font-size:9px;font-weight:700;letter-spacing:.05em}.detail b{display:block;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.detail b.ok{color:var(--mint)}.detail b.warn{color:var(--amber)}.detail b.error{color:var(--coral)}
.message{min-height:40px;margin-top:14px;padding:10px 12px;border-radius:12px;background:rgba(237,248,246,.72);color:var(--accent-deep);font-size:11px;line-height:1.45}.message.error{background:#fff4f1;color:#a84e40}.footer-note{display:flex;justify-content:space-between;gap:16px;margin-top:16px;color:#809397;font-size:10px}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(42,157,143,.28)}50%{box-shadow:0 0 0 5px rgba(42,157,143,0)}}
@media(max-width:900px){main{padding:20px 16px 40px}.dashboard{grid-template-columns:1fr}.controls{order:-1}.metrics{grid-template-columns:repeat(2,1fr)}.top-actions{position:absolute;top:24px;right:16px}.topbar{align-items:flex-start;padding-right:235px}.brand .sub{max-width:280px}}
@media(max-width:560px){main{padding:18px 12px 32px}.topbar{margin-bottom:16px;padding-right:0}.top-actions{position:static;align-self:flex-start;margin-top:12px}.health{margin-top:0}.topbar{flex-direction:column;gap:0}.brand-mark{width:46px;height:46px;border-radius:15px}.brand h1{font-size:25px}.brand .sub{font-size:12px}.controls{padding:16px;border-radius:20px}.camera-panel{padding:10px;border-radius:20px}.panel-head{padding:5px 5px 11px}.preview{border-radius:15px}.metrics{gap:7px}.metric{padding:11px}.metric strong{font-size:14px}.detail-list{grid-template-columns:1fr}.timer-grid{grid-template-columns:1fr}.follow-grid{grid-template-columns:1fr 1fr}.footer-note{flex-direction:column;gap:4px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<main>
<header class="topbar">
  <div class="brand">
    <span class="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="3.1" fill="currentColor"/><path d="M16 12.4c-2.1-3.9-2-7.2-.1-8.5 2.1-1.4 4.6 1 4.2 4.1-.2 1.7-1.3 3-2.5 4.1M19.4 16.8c3.8-1.7 7-1.4 8.1.5 1.2 2.1-1.3 4.4-4.3 3.8-1.7-.3-2.9-1.3-4-2.4M15.4 19.6c.7 4.1-.3 7.2-2.3 7.8-2.3.7-3.8-2.1-2.7-4.9.6-1.6 1.7-2.7 2.9-3.6M12.8 14.4c-4-.5-7-1.9-7-4 0-2.4 2.8-3.4 5.4-1.5 1.4 1 2.3 2.4 3 3.7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
    </span>
    <div>
      <p class="eyebrow">SMART AIR</p>
      <h1 data-i18n="brandTitle">轻风智能风扇</h1>
      <p class="sub" data-i18n="brandSubtitle">人体跟随 · 离线语音 · 智能巡视</p>
    </div>
  </div>
  <div class="top-actions">
    <div class="lang-switch" role="group" aria-label="Language"><button data-lang="zh">中文</button><button data-lang="en">EN</button></div>
    <div class="health" id="health"><i></i><span id="healthText" data-i18n="connecting">正在连接</span></div>
  </div>
</header>

<div class="dashboard">
  <section class="panel camera-panel">
    <div class="panel-head">
      <div><h2 data-i18n="cameraTitle">实时画面</h2><p data-i18n="cameraSubtitle">摄像头与人体检测框</p></div>
      <span class="live-chip" id="liveChip"><i></i><span id="liveText">画面待机</span></span>
    </div>
    <div class="preview">
      <img id="snapshot" alt="实时摄像头画面" data-i18n-alt="cameraAlt">
      <div class="camera-empty" id="cameraEmpty">
        <div><svg viewBox="0 0 32 32" fill="none"><path d="M5 9.5h22v16H5zM10 9.5l2-3h8l2 3M16 13.5a4.3 4.3 0 100 8.6 4.3 4.3 0 000-8.6z" stroke="currentColor" stroke-width="1.7"/></svg><strong data-i18n="cameraEmptyTitle">摄像头待机</strong><span data-i18n="cameraEmptySubtitle">打开风扇后开始检测与跟随</span></div>
      </div>
      <div id="overlay"></div>
    </div>
    <div class="metrics">
      <div class="metric"><span data-i18n="metricFan">风扇状态</span><strong id="fan">—</strong></div>
      <div class="metric"><span data-i18n="metricLevel">当前档位</span><strong id="level">—</strong></div>
      <div class="metric"><span data-i18n="metricState">运行状态</span><strong id="follow">—</strong></div>
      <div class="metric"><span data-i18n="metricTimer">定时剩余</span><strong id="timer">—</strong></div>
    </div>
  </section>

  <aside class="panel controls">
    <div class="control-title">
      <div><p class="eyebrow">DEVICE CONTROL</p><h2 data-i18n="deviceControl">设备控制</h2><p id="lastAction" data-i18n="waiting">等待操作</p></div>
      <span class="state-pill" id="statePill">已关闭</span>
    </div>

    <div class="section-label"><h3 data-i18n="power">电源</h3><span data-i18n="powerHint">打开后启动摄像头</span></div>
    <div class="power-grid">
      <button class="primary" data-cmd="fan_on" data-i18n="fanOn">打开风扇</button>
      <button class="danger" data-cmd="fan_off" data-i18n="fanOff">关闭风扇</button>
    </div>

    <div class="section-label"><h3 data-i18n="fanLevel">风力档位</h3><span id="levelHint">当前二档</span></div>
    <div class="gear-grid">
      <button data-cmd="level_low"><b data-i18n="level1">一档</b><small data-i18n="level1Hint">轻柔</small></button>
      <button data-cmd="level_medium"><b data-i18n="level2">二档</b><small data-i18n="level2Hint">舒适</small></button>
      <button data-cmd="level_high"><b data-i18n="level3">三档</b><small data-i18n="level3Hint">清凉</small></button>
      <button data-cmd="level_max"><b data-i18n="level4">四档</b><small data-i18n="level4Hint">强风</small></button>
    </div>

    <div class="section-label"><h3 data-i18n="follow">人体跟随</h3><span data-i18n="followHint">摄像头自动寻找方向</span></div>
    <div class="follow-grid">
      <button data-cmd="follow_on" data-i18n="followOn">开启跟随</button>
      <button class="danger" data-cmd="follow_off" data-i18n="followOff">停止跟随</button>
    </div>

    <div class="section-label"><h3 data-i18n="timerTitle">定时关机</h3><span id="timerHint">未设置</span></div>
    <div class="timer-grid">
      <button data-cmd="timer_10m" data-i18n="timer10">10 分钟</button>
      <button data-cmd="timer_half_hour" data-i18n="timer30">30 分钟</button>
      <button data-cmd="timer_1h" data-i18n="timer60">1 小时</button>
    </div>
    <div class="timer-grid timer-cancel" style="margin-top:8px"><button data-cmd="timer_cancel" data-i18n="timerCancel">取消定时</button></div>

    <div class="setting-card">
      <div class="setting-row">
        <div class="setting-copy"><strong data-i18n="autoOff">无人自动关机</strong><span id="autoOffHint">无人超过 60 秒后关闭</span><small data-i18n="autoOffVoice">语音可说：小风小风，关闭自动关机</small></div>
        <label class="switch" aria-label="无人自动关机">
          <input id="autoOffToggle" type="checkbox" checked>
          <span class="switch-track"></span>
        </label>
      </div>
    </div>

    <div class="detail-list">
      <div class="detail"><span data-i18n="servoAngle">舵机角度</span><b id="angle">—</b></div>
      <div class="detail"><span data-i18n="targetPosition">目标位置</span><b id="target">—</b></div>
      <div class="detail"><span data-i18n="visionStatus">视觉检测</span><b id="vision">—</b></div>
      <div class="detail"><span data-i18n="voiceStatus">语音服务</span><b id="voice">—</b></div>
    </div>
    <div class="message" id="message" aria-live="polite" data-i18n="ready">控制器已就绪</div>
    <div class="footer-note"><span data-i18n="footerBrand">轻风 Smart Fan</span><span id="uptime">运行时间 —</span></div>
  </aside>
</div>
</main>
<script>
const $ = s => document.querySelector(s);
const I18N = {
  zh: {
    brandTitle: '轻风智能风扇', brandSubtitle: '人体跟随 · 离线语音 · 智能巡视', footerBrand: '轻风 Smart Fan', connecting: '正在连接', online: '设备在线', disconnected: '连接断开',
    cameraTitle: '实时画面', cameraSubtitle: '摄像头与人体检测框', cameraAlt: '实时摄像头画面', cameraEmptyTitle: '摄像头待机', cameraEmptySubtitle: '打开风扇后开始检测与跟随',
    metricFan: '风扇状态', metricLevel: '当前档位', metricState: '运行状态', metricTimer: '定时剩余', deviceControl: '设备控制', waiting: '等待操作',
    power: '电源', powerHint: '打开后启动摄像头', fanOn: '打开风扇', fanOff: '关闭风扇', fanRunning: '运行中', fanStopped: '已关闭',
    fanLevel: '风力档位', level1: '一档', level2: '二档', level3: '三档', level4: '四档', level1Hint: '轻柔', level2Hint: '舒适', level3Hint: '清凉', level4Hint: '强风',
    follow: '人体跟随', followHint: '摄像头自动寻找方向', followOn: '开启跟随', followOff: '停止跟随',
    timerTitle: '定时关机', timer10: '10 分钟', timer30: '30 分钟', timer60: '1 小时', timerCancel: '取消定时', timerNotSet: '未设置',
    autoOff: '无人自动关机', autoOffVoice: '语音可说：小风小风，关闭自动关机', autoOffHint: '无人超过{time}后关闭', autoOffDisabled: '已关闭，将持续巡视',
    servoAngle: '舵机角度', targetPosition: '目标位置', visionStatus: '视觉检测', voiceStatus: '语音服务', ready: '控制器已就绪',
    person: '人体', noPerson: '无人', personDetected: '有人 · {count} 个目标', cameraOnline: '画面在线', cameraNoPerson: '在线 · 无人', cameraStandby: '摄像头待机', cameraOffline: '画面离线',
    livePerson: '检测到人体', listening: '监听中', voiceOff: '已关闭', voiceUnavailable: '未就绪', unknown: '未知', executing: '正在执行…', completed: '操作已完成', operationFailed: '操作失败：',
    awake: '已唤醒', voiceHeard: '已识别：{command}', voiceAwake: '已唤醒 · {language} · {seconds}秒',
    levelHint: '当前档位', uptime: '运行时间 —', uptimeValue: '运行 {time}',
    targetNoPerson: '无人', targetValue: '{percent}% · {reason}', targetDetecting: '检测中',
    reason_continuity: '连续目标', reason_cached: '短时保持', reason_accepted: '已确认', reason_switch_pending: '跳变确认中', reason_no_size_qualified_person: '尺寸不足',
    behavior_follow: '跟随中', behavior_search: '正在巡视', behavior_standby: '待机中', behavior_manual: '手动运行', behavior_off: '已关闭',
    state_followRunning: '跟随中', state_searching: '正在巡视', state_standby: '待机中', state_manual: '手动运行', state_off: '已关闭', statePerson: '人体检测'
  },
  en: {
    brandTitle: 'Breeze Smart Fan', brandSubtitle: 'Person tracking · Offline voice · Smart search', footerBrand: 'Breeze Smart Fan', connecting: 'Connecting', online: 'Device online', disconnected: 'Disconnected',
    cameraTitle: 'Live camera', cameraSubtitle: 'Camera feed and person detection', cameraAlt: 'Live camera feed', cameraEmptyTitle: 'Camera on standby', cameraEmptySubtitle: 'Turn on the fan to start tracking',
    metricFan: 'Fan status', metricLevel: 'Fan level', metricState: 'Mode', metricTimer: 'Timer left', deviceControl: 'Device control', waiting: 'Waiting for a command',
    power: 'Power', powerHint: 'Starts the camera and tracking', fanOn: 'Turn on', fanOff: 'Turn off', fanRunning: 'Running', fanStopped: 'Off',
    fanLevel: 'Fan level', level1: 'Level 1', level2: 'Level 2', level3: 'Level 3', level4: 'Level 4', level1Hint: 'Gentle', level2Hint: 'Comfort', level3Hint: 'Cool', level4Hint: 'Maximum',
    follow: 'Person tracking', followHint: 'The camera finds your direction', followOn: 'Start tracking', followOff: 'Stop tracking',
    timerTitle: 'Auto-off timer', timer10: '10 min', timer30: '30 min', timer60: '1 hour', timerCancel: 'Cancel timer', timerNotSet: 'Not set',
    autoOff: 'Auto shutdown', autoOffVoice: 'Voice: Hey Fan, disable auto shutdown', autoOffHint: 'Turns off after {time} without a person', autoOffDisabled: 'Off — searching will continue',
    servoAngle: 'Servo angle', targetPosition: 'Target position', visionStatus: 'Vision', voiceStatus: 'Voice', ready: 'Controller ready',
    person: 'Person', noPerson: 'No person', personDetected: 'Person · {count} target(s)', cameraOnline: 'Camera online', cameraNoPerson: 'Online · No person', cameraStandby: 'Camera standby', cameraOffline: 'Camera offline',
    livePerson: 'Person detected', listening: 'Listening', voiceOff: 'Off', voiceUnavailable: 'Not ready', unknown: 'Unknown', executing: 'Working…', completed: 'Done', operationFailed: 'Operation failed: ',
    awake: 'Awake', voiceHeard: 'Heard: {command}', voiceAwake: 'Awake · {language} · {seconds}s',
    levelHint: 'Current level', uptime: 'Uptime —', uptimeValue: 'Uptime {time}',
    targetNoPerson: 'No person', targetValue: '{percent}% · {reason}', targetDetecting: 'Detecting',
    reason_continuity: 'Continuous target', reason_cached: 'Short hold', reason_accepted: 'Confirmed', reason_switch_pending: 'Position confirming', reason_no_size_qualified_person: 'Box too small',
    behavior_follow: 'Tracking', behavior_search: 'Searching', behavior_standby: 'Standby', behavior_manual: 'Manual', behavior_off: 'Off',
    state_followRunning: 'Tracking', state_searching: 'Searching', state_standby: 'Standby', state_manual: 'Manual', state_off: 'Off', statePerson: 'Person detected'
  }
};
const LEVEL_NAMES = {
  zh: {low:'一档', medium:'二档', high:'三档', max:'四档'},
  en: {low:'Level 1', medium:'Level 2', high:'Level 3', max:'Level 4'}
};
const LEVEL_HINTS = {
  zh: {low:'轻柔模式', medium:'舒适模式', high:'清凉模式', max:'强风模式'},
  en: {low:'Gentle mode', medium:'Comfort mode', high:'Cool mode', max:'Maximum mode'}
};
const VOICE_COMMAND_NAMES = {
  zh: {fan_on:'打开风扇', fan_off:'关闭风扇', level_low:'一档', level_medium:'二档', level_high:'三档', level_max:'四档', follow_on:'开启跟随', follow_off:'停止跟随', timer_10m:'定时十分钟', timer_half_hour:'定时半小时', timer_1h:'定时一小时', timer_cancel:'取消定时', auto_off_on:'开启自动关机', auto_off_off:'关闭自动关机'},
  en: {fan_on:'Turn fan on', fan_off:'Turn fan off', level_low:'Level 1', level_medium:'Level 2', level_high:'Level 3', level_max:'Level 4', follow_on:'Start tracking', follow_off:'Stop tracking', timer_10m:'Timer 10 min', timer_half_hour:'Timer 30 min', timer_1h:'Timer 1 hour', timer_cancel:'Cancel timer', auto_off_on:'Enable auto shutdown', auto_off_off:'Disable auto shutdown'}
};
const ACTION_EN = {
  '风扇已打开':'Fan turned on', '风扇已关闭，摄像头和舵机进入待机':'Fan turned off; camera and servo are on standby',
  '人体跟随已开启':'Person tracking enabled', '人体跟随已停止':'Person tracking disabled', '定时已取消':'Timer cancelled',
  '无人自动关机已开启':'Auto shutdown enabled', '无人自动关机已关闭':'Auto shutdown disabled',
  '定时到期，风扇已关闭':'Timer expired; fan turned off', '无人，开始缓慢巡视':'No person found; starting a slow search',
  '巡视已找到人员':'Person found during search', '长时间无人，已进入待机':'No person for a long time; entering standby',
  '风扇未开启，命令未执行':'Fan is off; command was not executed', startup:'Ready'
};
let status = {};
let streamOn = false;
let autoBusy = false;
let currentLang = localStorage.getItem('smartFanLanguage') || ((navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en');
if (!['zh', 'en'].includes(currentLang)) currentLang = 'zh';
function tr(key) { return I18N[currentLang][key] || I18N.zh[key] || key; }
function fmt(value, vars = {}) { return Object.entries(vars).reduce((out, [key, val]) => out.replaceAll(`{${key}}`, String(val)), value); }
function fmtSec(value) {
  if (value == null) return tr('timerNotSet');
  value = Math.max(0, Math.round(value));
  const h = Math.floor(value / 3600), m = Math.floor((value % 3600) / 60), s = value % 60;
  if (currentLang === 'en') return h ? `${h} hr${m ? ` ${m} min` : ''}` : (m ? `${m} min${s ? ` ${s} sec` : ''}` : `${s} sec`);
  if (h) return `${h}小时${m ? `${m}分` : ''}`;
  if (m) return s ? `${m}分${s}秒` : `${m}分钟`;
  return `${s}秒`;
}
function localizeAction(text) {
  if (!text) return tr('waiting');
  if (currentLang !== 'en') return text;
  if (ACTION_EN[text]) return ACTION_EN[text];
  const level = text.match(/^档位切换为\s*(\w+)$/);
  if (level) return `${LEVEL_NAMES.en[level[1]] || level[1]} selected`;
  const timer = text.match(/^定时已设置\s*(\d+)\s*秒$/);
  if (timer) return `Timer set for ${fmtSec(Number(timer[1]))}`;
  return text;
}
function voiceLanguageName(code) {
  if (code === 'zh') return currentLang === 'zh' ? '中文' : 'Chinese';
  return 'English';
}
function applyLanguage(language) {
  currentLang = language;
  localStorage.setItem('smartFanLanguage', language);
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  document.title = language === 'zh' ? '轻风 · 智能风扇' : 'Breeze · Smart Fan';
  document.querySelectorAll('[data-i18n]').forEach(el => { if (!['healthText','lastAction'].includes(el.id)) el.textContent = tr(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-alt]').forEach(el => el.alt = tr(el.dataset.i18nAlt));
  document.querySelectorAll('[data-lang]').forEach(btn => btn.classList.toggle('active', btn.dataset.lang === language));
  fetch('/api/language', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({language})}).catch(() => {});
  if (!status.app) setMessage(tr('ready'));
  if (status.app) render(status);
}
function setText(id, text, cls = '') { const el = $('#' + id); el.textContent = text; el.className = cls; }
function setMessage(text, error = false) { const el = $('#message'); el.textContent = text; el.classList.toggle('error', error); }
function render(s) {
  status = s;
  const f = s.fan || {}, v = s.vision || {}, q = s.voice || {}, b = s.behavior || {};
  const health = $('#health'); health.className = 'health ' + (s.app?.running ? 'online' : 'offline');
  $('#healthText').textContent = s.app?.running ? tr('online') : tr('disconnected');
  setText('fan', f.on ? tr('fanRunning') : tr('fanStopped'), f.on ? 'ok' : 'off');
  setText('level', LEVEL_NAMES[currentLang][f.level] || f.level || '—', 'hot');
  $('#levelHint').textContent = LEVEL_HINTS[currentLang][f.level] || tr('levelHint');
  const behavior = b.state || 'off';
  setText('follow', tr('behavior_' + behavior), behavior === 'search' ? 'warn' : (behavior === 'follow' ? 'hot' : ''));
  setText('timer', fmtSec(f.timer_remaining_sec), f.timer_remaining_sec == null ? '' : 'warn');
  $('#timerHint').textContent = fmtSec(f.timer_remaining_sec);
  $('#statePill').textContent = tr('state_' + behavior);
  $('#lastAction').textContent = localizeAction(f.last_action);
  const connected = !!v.connected;
  $('#cameraEmpty').classList.toggle('hidden', connected);
  $('#liveChip').classList.toggle('on', connected);
  $('#liveText').textContent = connected ? (v.valid ? tr('livePerson') : tr('cameraOnline')) : (v.paused ? tr('cameraStandby') : tr('cameraOffline'));
  const img = $('#snapshot');
  if (connected) { if (!streamOn) { img.src = '/stream.mjpg?t=' + Date.now(); streamOn = true; } }
  else if (streamOn) { img.removeAttribute('src'); streamOn = false; }
  setText('angle', f.servo_angle == null ? '—' : Number(f.servo_angle).toFixed(1) + '°');
  const reason = v.selection?.reason || '';
  const reasonText = reason ? tr('reason_' + reason) : tr('targetDetecting');
  setText('target', v.target_x == null ? tr('targetNoPerson') : fmt(tr('targetValue'), {percent: Math.round(v.target_x * 100), reason: reasonText}));
  setText('vision', connected ? (v.valid ? fmt(tr('personDetected'), {count: v.count}) : tr('cameraNoPerson')) : (v.paused ? tr('state_standby') : tr('cameraOffline')), connected && v.valid ? 'ok' : (connected ? 'warn' : ''));
  const voiceLanguages = (q.languages || []).map(voiceLanguageName).join(' / ');
  const activeVoiceLanguage = voiceLanguageName(q.awake_language || q.last_language);
  const recentVoiceCommand = q.last_command && q.last_command_age_sec != null && q.last_command_age_sec <= 8;
  let voiceText = q.last_error || tr('voiceUnavailable');
  if (!q.enabled) voiceText = tr('voiceOff');
  else if (q.listening && recentVoiceCommand) voiceText = fmt(tr('voiceHeard'), {command: (VOICE_COMMAND_NAMES[currentLang] || VOICE_COMMAND_NAMES.en)[q.last_command] || q.last_command});
  else if (q.listening && q.awake) voiceText = fmt(tr('voiceAwake'), {language: activeVoiceLanguage, seconds: Math.max(1, Math.ceil(q.wake_remaining_sec || 0))});
  else if (q.listening) voiceText = `${tr('listening')}${voiceLanguages ? ' · ' + voiceLanguages : ''}`;
  setText('voice', voiceText, q.listening ? (q.awake ? 'hot' : 'ok') : 'warn');
  const autoOn = b.auto_off_enabled !== false;
  const after = fmtSec(b.auto_off_after_sec ?? 60);
  $('#autoOffHint').textContent = autoOn ? fmt(tr('autoOffHint'), {time: after}) : tr('autoOffDisabled');
  if (!autoBusy) $('#autoOffToggle').checked = autoOn;
  $('#uptime').textContent = s.app?.uptime_sec == null ? tr('uptime') : fmt(tr('uptimeValue'), {time: fmtSec(s.app.uptime_sec)});
  document.querySelectorAll('[data-cmd]').forEach(btn => {
    const c = btn.dataset.cmd;
    const active = (c === 'fan_on' && f.on) || (c === 'fan_off' && !f.on) || (c === 'follow_on' && f.on && f.follow) || (c === 'follow_off' && f.on && !f.follow) || (c === 'level_' + f.level);
    btn.classList.toggle('active', active);
  });
  const box = $('#overlay'); box.innerHTML = '';
  const p = v.person;
  if (p && v.valid) {
    const d = document.createElement('div'); d.className = 'person-box';
    const w = Number(p.x2) - Number(p.x1), h = Number(p.y2) - Number(p.y1);
    Object.assign(d.style, {left:`${Number(p.x1)*100}%`, top:`${Number(p.y1)*100}%`, width:`${w*100}%`, height:`${h*100}%`});
    d.dataset.label = `${tr('person')} ${Number(p.score).toFixed(2)}`; box.appendChild(d);
  }
}
async function refresh() {
  try {
    const response = await fetch('/api/status', {cache: 'no-store'});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    render(await response.json());
  } catch (error) {
    $('#health').className = 'health offline'; $('#healthText').textContent = tr('disconnected');
  }
}
async function command(cmd) {
  setMessage(tr('executing'));
  try {
    const response = await fetch('/api/command', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({command: cmd, language: currentLang, require_fan_on: true})});
    const result = await response.json();
    if (response.status === 409 && result.code === 'fan_required') {
      setMessage(result.action || tr('fanRequired'));
      await refresh();
      return;
    }
    if (!response.ok || !result.ok) throw new Error(result.error || ('HTTP ' + response.status));
    setMessage(localizeAction(result.action) || tr('completed'));
    await refresh();
  } catch (error) {
    setMessage(tr('operationFailed') + error.message, true);
  }
}
document.querySelectorAll('[data-cmd]').forEach(btn => btn.addEventListener('click', () => command(btn.dataset.cmd)));
document.querySelectorAll('[data-lang]').forEach(btn => btn.addEventListener('click', () => applyLanguage(btn.dataset.lang)));
$('#autoOffToggle').addEventListener('change', async event => {
  const enabled = event.target.checked;
  autoBusy = true; event.target.disabled = true;
  try { await command(enabled ? 'auto_off_on' : 'auto_off_off'); }
  finally { autoBusy = false; event.target.disabled = false; await refresh(); }
});
applyLanguage(currentLang);
refresh(); setInterval(refresh, 500);
</script>
</body>
</html>'''


class WebApi:
    def __init__(
        self,
        cfg: dict[str, Any],
        status_fn: Callable[[], dict[str, Any]],
        command_fn: Callable[[str, str, bool], tuple[bool, str, str]],
        snapshot_path: str,
        language_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.status_fn = status_fn
        self.command_fn = command_fn
        self.snapshot_path = Path(snapshot_path)
        self.language_fn = language_fn
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "SmartFan/0.1"

            def log_message(self, fmt: str, *args: object) -> None:
                LOG.debug("%s - %s", self.address_string(), fmt % args)

            def _send(self, code: int, body: bytes, content_type: str = "", cache: str = "no-store") -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _json(self, code: int, obj: dict[str, Any]) -> None:
                self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

            def do_HEAD(self) -> None:
                self.do_GET()

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path in ("/", "/index.html"):
                    self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
                elif parsed.path == "/api/status":
                    self._json(200, api.status_fn())
                elif parsed.path == "/stream.mjpg":
                    api.stream_mjpeg(self)
                elif parsed.path == "/snapshot.jpg":
                    try:
                        data = api.snapshot_path.read_bytes()
                    except OSError:
                        self._send(404, b"snapshot unavailable", "text/plain; charset=utf-8")
                    else:
                        self._send(200, data, "image/jpeg", "no-store")
                else:
                    self._json(404, {"ok": False, "error": "not found"})

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path not in ("/api/command", "/api/language"):
                    self._json(404, {"ok": False, "error": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw = self.rfile.read(length) if length else b"{}"
                    body = json.loads(raw.decode("utf-8") or "{}")
                    command = str(body.get("command") or parse_qs(parsed.query).get("command", [""])[0])
                    language = str(body.get("language") or "zh")
                    require_fan_on = bool(body.get("require_fan_on", False))
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self._json(400, {"ok": False, "error": f"invalid request: {exc}"})
                    return
                if parsed.path == "/api/language":
                    if api.language_fn:
                        api.language_fn(language)
                    self._json(200, {"ok": True, "language": language})
                    return
                ok, message, code = api.command_fn(command, language, require_fan_on)
                status = 200 if ok else (409 if code == "fan_required" else 400)
                self._json(status, {"ok": ok, "action": message, "error": "" if ok else message, "code": code})

        listen = str(self.cfg["listen"])
        port = int(self.cfg["port"])
        self.server = ThreadingHTTPServer((listen, port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="web", daemon=True)
        self.thread.start()
        LOG.info("web UI: http://%s:%d/", listen, port)

    def stream_mjpeg(self, handler: BaseHTTPRequestHandler) -> None:
        boundary = "frame"
        handler.send_response(200)
        handler.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        handler.send_header("Pragma", "no-cache")
        handler.end_headers()
        last_stamp: int | None = None
        try:
            while self.server:
                try:
                    stat = self.snapshot_path.stat()
                except OSError:
                    time.sleep(0.1)
                    continue
                if stat.st_mtime_ns == last_stamp:
                    time.sleep(0.02)
                    continue
                data = self.snapshot_path.read_bytes()
                last_stamp = stat.st_mtime_ns
                handler.wfile.write(f"--{boundary}\r\n".encode())
                handler.wfile.write(b"Content-Type: image/jpeg\r\n")
                handler.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode())
                handler.wfile.write(data)
                handler.wfile.write(b"\r\n")
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            handler.close_connection = True

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=3.0)
