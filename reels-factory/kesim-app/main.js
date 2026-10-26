const {app,BrowserWindow,session,Menu,Tray,ipcMain,safeStorage,nativeImage,shell}=require("electron");
const path=require("path");
app.commandLine.appendSwitch("autoplay-policy","no-user-gesture-required");

/* SelfEdit (kendini geliştiren efekt motoru). Yüklenemezse editör yine de normal açılır. */
let host=null;
try{host=require("./selfedit/host.js")}catch(e){console.error("[selfedit] yüklenemedi:",e)}
/* Reels Fabrikası bağlantısı (Fabrika sekmesi, Claude/MCP kontrolü). Yüklenemezse Kesim yine açılır. */
let fabrika=null;
try{fabrika=require("./fabrika/host.js")}catch(e){console.error("[fabrika] yüklenemedi:",e)}
const startHidden=process.argv.includes("--arka-plan");

if(!app.requestSingleInstanceLock()){app.quit()}
else{
  let w=null;
  const showWindow=()=>{if(!w||w.isDestroyed())return;if(w.isMinimized())w.restore();w.show();w.focus()};
  app.on("second-instance",showWindow);
  app.whenReady().then(()=>{
    Menu.setApplicationMenu(null);
    session.defaultSession.setPermissionRequestHandler((wc,perm,cb)=>cb(true));
    w=new BrowserWindow({width:1440,height:900,title:"Kesim",backgroundColor:"#0f1115",autoHideMenuBar:true,show:false,
      webPreferences:{contextIsolation:true,preload:path.join(__dirname,"preload.js")}});
    w.on("close",e=>{if(host&&host.shouldHideOnClose()){e.preventDefault();w.hide()}});
    w.once("ready-to-show",()=>{
      // Windows ile başlatılan arka plan oturumunda pencere gizli kalır; ayar kapalıysa normal açılır
      if(startHidden&&host&&host.config().background)return;
      w.show();
    });
    w.loadFile(__dirname+"/index.html");
    if(fabrika){try{fabrika.init({app,ipcMain,shell,getWindow:()=>w})}catch(e){console.error("[fabrika] başlatılamadı:",e)}}
    if(host){try{host.init({app,BrowserWindow,ipcMain,safeStorage,Tray,Menu,nativeImage,getWindow:()=>w,showWindow})}catch(e){console.error("[selfedit] başlatılamadı:",e)}}
  });
  app.on("window-all-closed",()=>{if(!(host&&host.keepAlive()))app.quit()});
}
