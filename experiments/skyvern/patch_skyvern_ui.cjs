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

const readyState = "const H=u.length>0;return";
const readyStateWithLogin =
  "const H=u.length>0,Q=blogHubHashnodeLoginComplete(y);return";
const streamRender = "H?i.jsx(q5e,{";
const streamRenderWithLogin =
  "Q?i.jsx(blogHubHashnodeLoginCompleteView,{}):H?i.jsx(q5e,{";
if (
  browserSession.split(readyState).length !== 2 ||
  browserSession.split(streamRender).length !== 2
) {
  throw new Error("Pinned Skyvern browser-session render changed");
}
browserSession = browserSession
  .replace(readyState, readyStateWithLogin)
  .replace(streamRender, streamRenderWithLogin);

const loginCompleteHelpers = `function blogHubHashnodeLoginComplete(t){
  if(new URLSearchParams(window.location.search).get("purpose")!=="hashnode-login")return false;
  try{
    const e=new URL(t),n=e.hostname.toLowerCase();
    return(n==="hashnode.com"||n==="www.hashnode.com")&&e.hash==="#bloghub-authenticated";
  }catch{return false}
}
function blogHubHashnodeLoginCompleteView(){
  return i.jsx("main",{style:{minHeight:"100vh",display:"grid",placeItems:"center",background:"#0d0f14",color:"#e7eaf2",fontFamily:"Inter,ui-sans-serif,system-ui,sans-serif"},children:i.jsxs("section",{style:{width:"min(460px,calc(100vw - 48px))",textAlign:"center"},children:[
    i.jsx("div",{style:{display:"inline-block",marginBottom:"18px",padding:"6px 10px",border:"1px solid #2f7d4a",borderRadius:"5px",color:"#71d892",fontSize:"12px",fontWeight:700},children:"Signed in"}),
    i.jsx("h1",{style:{margin:"0 0 12px",fontSize:"28px",lineHeight:1.2,fontWeight:700},children:"Hashnode login successful"}),
    i.jsx("p",{style:{margin:"0 auto 24px",color:"#9aa3b7",fontSize:"15px",lineHeight:1.6},children:"Close this tab to save and verify the browser profile, then return to BlogHub."}),
    i.jsx("button",{type:"button",onClick:()=>window.close(),style:{padding:"10px 18px",border:0,borderRadius:"5px",background:"#6366f1",color:"#fff",font:"inherit",fontWeight:600,cursor:"pointer"},children:"Close tab"})
  ]})})
}`;

source =
  source.slice(0, browserSessionStart) +
  loginCompleteHelpers +
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
fs.writeFileSync(indexPath, indexHtml);
