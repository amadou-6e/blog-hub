const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const assets = "/app/dist.template/assets";
const indexPath = "/app/dist.template/index.html";
let indexHtml = fs.readFileSync(indexPath, "utf8");
const bundleMatch = indexHtml.match(/assets\/(index-[^"']+\.js)/);
const bundleName = bundleMatch?.[1];
if (!bundleName) throw new Error("Pinned Skyvern UI entry bundle was not found");

const bundle = path.join(assets, bundleName);
let source = fs.readFileSync(bundle, "utf8");
const componentStart = source.indexOf("function X5e({inputWsUrl");
const componentEnd = source.indexOf("function W5(", componentStart);
if (componentStart < 0 || componentEnd < 0) {
  throw new Error("Pinned Skyvern CDP viewer component changed");
}

let component = source.slice(componentStart, componentEnd);
const controlState = "const[s,a]=x.useState(!1),[o,l]=x.useState(!1)";
const disconnectedControlState = "l(!1),v.current=!1,a(!1),h.current=null";
if (
  component.split(controlState).length !== 2 ||
  component.split(disconnectedControlState).length !== 2
) {
  throw new Error("Pinned Skyvern CDP control state changed");
}

// This image is the browser in BlogHub's dedicated login window. Acquire CDP
// control immediately and retain that intent across websocket reconnects.
component = component
  .replace(controlState, "const[s,a]=x.useState(!0),[o,l]=x.useState(!1)")
  .replace(
    disconnectedControlState,
    "l(!1),v.current=!0,a(!0),h.current=null",
  );

const pointerCoordinates =
  "function tL(t,e,n){return W5e(t.clientX,t.clientY,t.currentTarget.getBoundingClientRect(),e,n)}";
const displayedPointerCoordinates =
  "function tL(t,e,n){const r=t.currentTarget.getBoundingClientRect();return W5e(t.clientX,t.clientY,r,r.width,r.height)}";
const wheelCoordinates =
  "const K=B.getBoundingClientRect(),U=W5e(M.clientX,M.clientY,K,n,r);";
const displayedWheelCoordinates =
  "const K=B.getBoundingClientRect(),U=W5e(M.clientX,M.clientY,K,K.width,K.height);";
if (
  source.split(pointerCoordinates).length !== 2 ||
  component.split(wheelCoordinates).length !== 2
) {
  throw new Error("Pinned Skyvern CDP coordinate mapping changed");
}

// HiDPI screenshot polling produces bitmap dimensions that differ from the
// browser's CSS viewport. Input.dispatchMouseEvent expects CSS coordinates,
// so map pointer and wheel input against the displayed image instead of the
// stale screencast metadata retained by the stock viewer.
component = component.replace(wheelCoordinates, displayedWheelCoordinates);

const anchor = "},[]),j=x.useCallback(P=>{if(!e||!s)return;";
if (component.split(anchor).length !== 2) {
  throw new Error("Pinned Skyvern CDP input hook changed");
}

const resizeEffect = `},[]);x.useEffect(()=>{
  if(!e)return;
  let I=null;
  let A=null;
  let P=null;
  let L=null;
  const M=()=>{
    const B=p.current;
    if(!B)return;
    if(P!==B){
      L?.disconnect();
      P=B;
      L=new ResizeObserver(M);
      L.observe(P);
    }
    I!==null&&clearTimeout(I);
    I=setTimeout(()=>{
      const K=h.current;
      if(!K||K.readyState!==WebSocket.OPEN||!P)return;
      const U=P.getBoundingClientRect();
      K.send(JSON.stringify({
        kind:"viewportEvent",
        width:Math.round(U.width),
        height:Math.round(U.height),
        deviceScaleFactor:window.devicePixelRatio||1
      }));
      A!==null&&(clearInterval(A),A=null);
    },100);
  };
  window.visualViewport?.addEventListener("resize",M);
  M();
  A=setInterval(M,250);
  return()=>{
    I!==null&&clearTimeout(I);
    A!==null&&clearInterval(A);
    L?.disconnect();
    window.visualViewport?.removeEventListener("resize",M);
  };
},[e]);const j=x.useCallback(P=>{if(!e||!s)return;`;

component = component.replace(anchor, resizeEffect);
source = source.slice(0, componentStart) + component + source.slice(componentEnd);
source = source.replace(pointerCoordinates, displayedPointerCoordinates);

const browserSessionStart = source.indexOf("function X5({browserSessionId:");
const browserSessionEnd = source.indexOf("const H5e=", browserSessionStart);
if (browserSessionStart < 0 || browserSessionEnd < 0) {
  throw new Error("Pinned Skyvern browser-session component changed");
}

let browserSession = source.slice(browserSessionStart, browserSessionEnd);
const backendWaitMessage = "Just waiting for the backend to hand us a browser.";
if (browserSession.split(backendWaitMessage).length !== 2) {
  throw new Error("Pinned Skyvern browser startup message changed");
}
browserSession = browserSession.replace(backendWaitMessage, "Starting the browser.");

source =
  source.slice(0, browserSessionStart) +
  browserSession +
  source.slice(browserSessionEnd);

const authBootstrap =
  'XUe().catch(t=>console.error("[ui-session] failed to initialize:",t));w7e.createRoot';
if (source.split(authBootstrap).length !== 2) {
  throw new Error("Pinned Skyvern UI session bootstrap changed");
}

// The stock bundle renders before its temporary UI credential is ready. On a
// direct browser-session URL, that races the initial session query and leaves
// the viewer displaying a false completed state after the query returns 403.
source = source.replace(
  authBootstrap,
  'await XUe().catch(t=>console.error("[ui-session] failed to initialize:",t));w7e.createRoot',
);
fs.writeFileSync(bundle, source);

// The base image's filename contains the upstream build hash. Since this
// script changes its contents, retain content-addressed caching by giving the
// patched file a new hash and updating the HTML reference. Otherwise normal
// browsers can retain an older BlogHub viewer while clean test contexts work.
const digest = crypto.createHash("sha256").update(source).digest("hex").slice(0, 12);
const patchedBundleName = bundleName.replace(/\.js$/, `-bloghub-${digest}.js`);
fs.renameSync(bundle, path.join(assets, patchedBundleName));
indexHtml = indexHtml.replace(`assets/${bundleName}`, `assets/${patchedBundleName}`);
const handoffScript = `<script>(()=>{
  const params=new URLSearchParams(window.location.search);
  const purpose=params.get("purpose")||"";
  const platform=purpose.endsWith("-login")?purpose.slice(0,-6):"";
  if(!["hashnode","medium"].includes(platform))return;
  let returnOrigin="";
  try{
    const parsed=new URL(params.get("returnOrigin")||"");
    if(parsed.protocol==="http:"||parsed.protocol==="https:")returnOrigin=parsed.origin;
  }catch{}
  if(!returnOrigin)return;

  const notify=()=>window.opener?.postMessage({
    type:"bloghub-browser-login-ready",platform
  },returnOrigin);
  notify();
  const heartbeat=window.setInterval(notify,1000);

  function showConfirmation(){
    if(document.getElementById("bloghub-login-complete"))return;
    const label=platform==="medium"?"Medium":"Hashnode";
    const overlay=document.createElement("main");
    overlay.id="bloghub-login-complete";
    overlay.setAttribute("role","status");
    overlay.style.cssText="position:fixed;inset:0;z-index:2147483647;display:grid;place-items:center;background:#0d0f14;color:#e7eaf2;font-family:Inter,ui-sans-serif,system-ui,sans-serif";
    const content=document.createElement("section");
    content.style.cssText="width:min(460px,calc(100vw - 48px));text-align:center";
    const badge=document.createElement("div");
    badge.textContent="Signed in";
    badge.style.cssText="display:inline-block;margin-bottom:18px;padding:6px 10px;border:1px solid #2f7d4a;border-radius:5px;color:#71d892;font-size:12px;font-weight:700";
    const title=document.createElement("h1");
    title.textContent=label+" login successful";
    title.style.cssText="margin:0 0 12px;font-size:28px;line-height:1.2;font-weight:700";
    const copy=document.createElement("p");
    copy.textContent="Close this tab to save and verify the browser profile, then return to BlogHub.";
    copy.style.cssText="margin:0 auto 24px;color:#9aa3b7;font-size:15px;line-height:1.6";
    const button=document.createElement("button");
    button.type="button";
    button.textContent="Close tab";
    button.style.cssText="padding:10px 18px;border:0;border-radius:5px;background:#6366f1;color:#fff;font:inherit;font-weight:600;cursor:pointer";
    button.addEventListener("click",()=>window.close());
    content.append(badge,title,copy,button);
    overlay.append(content);
    document.body.append(overlay);
  }

  window.addEventListener("message",event=>{
    if(event.source!==window.opener||event.origin!==returnOrigin)return;
    const data=event.data||{};
    if(data.type!=="bloghub-browser-login-state"||data.platform!==platform)return;
    if(data.loginPhase==="signed_in_pending_save")showConfirmation();
  });
  window.addEventListener("beforeunload",()=>window.clearInterval(heartbeat));
})();</script>`;
if (!indexHtml.includes("</body>")) {
  throw new Error("Pinned Skyvern UI document body changed");
}
indexHtml = indexHtml.replace("</body>", `${handoffScript}</body>`);
fs.writeFileSync(indexPath, indexHtml);
