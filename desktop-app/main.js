const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');

function createWindow() {
    const win = new BrowserWindow({
        width: 340,
        height: 460,
        transparent: true,
        frame: false,
        alwaysOnTop: true,
        resizable: false,
        hasShadow: false,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false // For MVP simplicity; normally use preload scripts
        }
    });

    // Make it definitively stay on top of everything
    win.setAlwaysOnTop(true, 'screen-saver', 1);
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

    win.loadFile('index.html');

    // DevTools only when explicitly requested (set MILO_DEVTOOLS=1).
    if (process.env.MILO_DEVTOOLS) {
        win.webContents.openDevTools({ mode: 'detach' });
    }

    ipcMain.on('minimize-window', () => win.minimize());
    ipcMain.on('close-window', () => win.close());
}

app.whenReady().then(() => {
    // Auto-allow microphone permissions for Web Speech API
    app.on('web-contents-created', (event, webContents) => {
        webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
            if (permission === 'media') {
                callback(true);
            } else {
                callback(false);
            }
        });
    });

    createWindow();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow();
        }
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});
