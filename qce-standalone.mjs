#!/usr/bin/env node
/**
 * QCE 独立模式启动脚本
 * 无需 NapCat 登录即可运行，用于浏览已导出的聊天记录和资源
 */
import { spawn, spawnSync } from 'node:child_process';
import { appendFileSync, mkdirSync, readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// macOS: 从浏览器下载并用「访达」解压的包，每个文件都会带上 com.apple.quarantine。
// Apple Silicon 的 AMFI 会在 execve() 时直接 SIGKILL 这种「被隔离 + 仅临时签名」的
// 二进制，且不会留下任何日志——表现为网页打不开却查不到任何报错。完整模式的
// launcher-user.sh 已经做了同样的清理，这里覆盖独立模式自己拉起 qce-server 的路径。
function clearQuarantine(target) {
    if (process.platform !== 'darwin') return;
    try {
        spawnSync('xattr', ['-cr', target], { stdio: 'ignore' });
    } catch {
        // 尽力而为：清不掉时后面的 spawn 会照常报错
    }
}

function securityConfigPath() {
    const override = (process.env.QCE_CONFIG_DIR || '').trim();
    const dir = override || path.join(os.homedir(), '.qq-chat-exporter');
    return path.join(dir, 'security.json');
}

function userConfigPath() {
    return path.join(os.homedir(), '.qq-chat-exporter', 'user-config.json');
}

function readAutoOpenBrowserSetting(configPath) {
    try {
        const value = JSON.parse(readFileSync(configPath, 'utf8'))?.autoOpenBrowser;
        return typeof value === 'boolean' ? value : true;
    } catch {
        return true; // 文件不存在/无法读取时沿用历史默认值（打开）
    }
}

function browserOpenCommand(url) {
    if (process.platform === 'darwin') return { cmd: 'open', args: [url] };
    if (process.platform === 'win32') return { cmd: 'cmd', args: ['/c', 'start', '', url] };
    return { cmd: 'xdg-open', args: [url] };
}

// 开关名与完整模式一致（plugins/qq-chat-exporter/runtime/rustBridge.mjs）：
// QCE_NO_AUTO_OPEN=1 是硬开关，优先于设置页的开关；未设置时才看持久化设置。
function tryOpenBrowser(url) {
    if (process.env.QCE_NO_AUTO_OPEN === '1') return;
    if (!readAutoOpenBrowserSetting(userConfigPath())) return;
    try {
        const { cmd, args } = browserOpenCommand(url);
        const child = spawn(cmd, args, { stdio: 'ignore', detached: true });
        child.on('error', () => {}); // 无图形界面的机器上没有浏览器可开，忽略即可
        child.unref();
    } catch {
        // 尽力而为：上面打印出来的链接才是真正的兜底
    }
}

// 等端口真正开始监听。security.json 在上一次运行后就已存在，所以不能只靠它
// 判断服务端是否就绪——端口被占用时 qce-server 会直接退出，那时报喜（更别说
// 自动弹一个必然打不开的浏览器标签）纯属误导。
async function waitForServer(child, port, timeoutMs = 15_000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        if (child.exitCode !== null) return false;
        const ready = await new Promise((resolve) => {
            const socket = net.createConnection({ host: '127.0.0.1', port });
            socket.once('connect', () => { socket.destroy(); resolve(true); });
            socket.once('error', () => resolve(false));
            socket.setTimeout(500, () => { socket.destroy(); resolve(false); });
        });
        if (ready) return true;
        await new Promise((resolve) => setTimeout(resolve, 200));
    }
    return false;
}

// Issue #457: 独立模式原本什么都不打印，用户卡在令牌输入框却无处可查。
async function announceLoginUrl(child, port) {
    if (!(await waitForServer(child, port))) return;   // 服务端自己会报错，不再叠加误导信息
    const configFile = securityConfigPath();
    for (let attempt = 0; attempt < 30; attempt++) {
        try {
            const config = JSON.parse(await readFile(configFile, 'utf8'));
            if (config.accessToken) {
                const url = `http://127.0.0.1:${port}/qce/auth?token=${encodeURIComponent(config.accessToken)}`;
                console.log('');
                console.log(`[QCE] Token: ${config.accessToken}`);
                console.log(`[QCE] 一键登录: ${url}`);
                console.log('[QCE] 此链接包含访问令牌，请勿分享给他人');
                console.log('');
                tryOpenBrowser(url);
                return;
            }
        } catch {
            // security.json 还没写出来，继续轮询
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    console.log(`[QCE] 未能读取访问令牌，请打开 ${configFile} 查看 accessToken 字段`);
}

async function main() {
    const port = parseInt(process.argv[2]) || 40653;
    const packageRoot = path.dirname(fileURLToPath(import.meta.url));
    const binary = path.join(
        packageRoot,
        process.platform === 'win32' ? 'qce-server.exe' : 'qce-server'
    );
    clearQuarantine(binary);

    const logDir = process.env.QCE_LOG_DIR || path.join(packageRoot, 'logs');
    mkdirSync(logDir, { recursive: true });
    const logFile = process.env.QCE_LOG_FILE || path.join(logDir, 'qce-runtime.log');
    const writeLog = (stream, prefix, chunk) => {
        const text = String(chunk);
        appendFileSync(logFile, `[${new Date().toISOString()}] ${prefix} ${text}${text.endsWith('\n') ? '' : '\n'}`);
        stream.write(text);
    };
    writeLog(process.stdout, '[qce-standalone]', 'starting standalone mode\n');
    const child = spawn(binary, [], {
        cwd: packageRoot,
        env: {
            ...process.env,
            QCE_SERVER_PORT: String(port),
            QCE_LOG_DIR: logDir,
            QCE_LOG_FILE: logFile
        },
        stdio: ['ignore', 'pipe', 'pipe']
    });
    child.stdout.on('data', (chunk) => writeLog(process.stdout, '[qce-server]', chunk));
    child.stderr.on('data', (chunk) => writeLog(process.stderr, '[qce-server]', chunk));
    child.on('error', (error) => {
        writeLog(process.stderr, '[qce-standalone]', `startup failed: ${error}\n`);
        process.exit(1);
    });
    child.on('exit', (code, signal) => {
        writeLog(process.stdout, '[qce-standalone]', `exited code=${code ?? 'null'} signal=${signal ?? 'null'}\n`);
        process.exit(code ?? (signal ? 1 : 0));
    });
    const stop = () => child.kill();
    process.on('SIGINT', stop);
    process.on('SIGTERM', stop);
    announceLoginUrl(child, port);
}

main();
