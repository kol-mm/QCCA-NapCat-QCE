/**
 * QQ Chat Exporter plugin entrypoint.
 * Supports both NapCat Shell and Framework modes.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PLUGIN_ROOT = path.resolve(__dirname);
const PROJECT_ROOT = path.resolve(PLUGIN_ROOT, '..', '..');

let apiLauncher = null;
let pluginLogger = console;

// 实时捕获状态：仅在 API 服务启动完成后才转发新消息。
let ingestReady = false;
let accessToken = null;
const INGEST_PORT = Number(process.env.QCE_SERVER_PORT || 40653);
const QCCA_PORT = Number(process.env.QCCA_API_PORT || 40655);

/**
 * @returns {'shell' | 'framework' | 'unknown'}
 */
function detectWorkingEnv(core) {
  const workingEnv = core?.context?.workingEnv;
  if (workingEnv === 1) return 'shell';
  if (workingEnv === 2) return 'framework';

  if (typeof process !== 'undefined') {
    if (process.versions?.electron) return 'framework';
    if (process.env?.NAPCAT_SHELL) return 'shell';
  }

  return 'unknown';
}

export function createFallbackCore(rawCore) {
  const safeCore = rawCore && typeof rawCore === 'object' ? rawCore : {};
  if (!safeCore.context || typeof safeCore.context !== 'object') {
    safeCore.context = {};
  }

  const logger = safeCore.context.logger;
  const existingLogger = logger && (typeof logger === 'object' || typeof logger === 'function')
    ? logger
    : {};
  const fallbacks = new Map([
    ['log', (...args) => console.log('[QCE]', ...args)],
    ['logError', (...args) => console.error('[QCE]', ...args)],
    ['logWarn', (...args) => console.warn('[QCE]', ...args)],
    ['logDebug', (...args) => console.debug('[QCE]', ...args)]
  ]);

  safeCore.context.logger = new Proxy(existingLogger, {
    get(target, property) {
      const value = Reflect.get(target, property, target);
      if (typeof value === 'function') {
        return value.bind(target);
      }
      if (typeof property === 'string' && fallbacks.has(property)) {
        return fallbacks.get(property);
      }
      return value;
    }
  });

  return safeCore;
}

/**
 * API adapter that wraps the real NapCat apis and provides fallback implementations
 * for methods that are missing or have different signatures in NapCat 4.18.6.
 *
 * This adapter receives the REAL NapCat APIs (from the bridge), not the stub Proxy.
 * It provides stub fallbacks for methods that don't exist or return wrong types.
 */
function createApiAdapter(apis) {
  // Known methods that QCE expects, organized by API namespace
  const knownMethods = {
    GroupApi: ['getGroups', 'fetchGroupDetail', 'getGroupMemberAll', 'getGroupFileCount'],
    FriendApi: ['getBuddy', 'getBuddyV2ExWithCate', 'getFriends'],
    WebApi: ['getGroupEssenceMsgAll'],
  };

  const stubs = {
    GroupApi: {
      getGroups: async () => [],
      fetchGroupDetail: async (groupCode) => ({ groupCode, groupName: 'Unknown' }),
      getGroupMemberAll: async () => ({ result: { infos: new Map() } }),
      getGroupFileCount: async () => ({ groupFileCounts: [] }),
    },
    FriendApi: {
      getBuddy: async () => [],
      getBuddyV2ExWithCate: async () => [],
      getFriends: async () => [],
    },
    WebApi: {
      getGroupEssenceMsgAll: async () => [],
    },
  };

  return new Proxy({}, {
    get(target, apiName) {
      if (!(apiName in target)) {
        target[apiName] = new Proxy({}, {
          get(apiTarget, methodName) {
            const methodList = knownMethods[apiName];
            const methodStubs = stubs[apiName];

            // If this is a known QCE method
            if (methodList && methodList.includes(methodName)) {
              // Try the real API first
              const realApi = apis?.[apiName];
              const realMethod = realApi?.[methodName];
              if (typeof realMethod === 'function') {
                return realMethod.bind(realApi);
              }
              // Fall back to stub
              return methodStubs?.[methodName] || (async () => []);
            }

            // For unknown methods, try real API first
            const realApi = apis?.[apiName];
            const realMethod = realApi?.[methodName];
            if (typeof realMethod === 'function') {
              return realMethod.bind(realApi);
            }
            return async () => ({ result: 0, errMsg: '' });
          }
        });
      }
      return target[apiName];
    }
  });
}

function pickFirstDefined(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null) {
      return value;
    }
  }

  return undefined;
}

function isContextLikeObject(value) {
  return !!(value && typeof value === 'object' && (
    Object.prototype.hasOwnProperty.call(value, 'core') ||
    Object.prototype.hasOwnProperty.call(value, '_ctx') ||
    Object.prototype.hasOwnProperty.call(value, 'ctx') ||
    Object.prototype.hasOwnProperty.call(value, 'obContext') ||
    Object.prototype.hasOwnProperty.call(value, 'oneBot') ||
    Object.prototype.hasOwnProperty.call(value, 'actions') ||
    Object.prototype.hasOwnProperty.call(value, 'instance') ||
    Object.prototype.hasOwnProperty.call(value, 'logger') ||
    Object.prototype.hasOwnProperty.call(value, 'router') ||
    Object.prototype.hasOwnProperty.call(value, 'pluginManager')
  ));
}

function normalizePluginArgs(arg0, arg1, arg2, arg3) {
  if (isContextLikeObject(arg0)) {
    const nestedCtx = arg0._ctx && typeof arg0._ctx === 'object'
      ? arg0._ctx
      : arg0.ctx && typeof arg0.ctx === 'object'
        ? arg0.ctx
        : undefined;
    const core = pickFirstDefined(
      arg0.core,
      nestedCtx?.core,
      arg0.NapCatCore,
      nestedCtx?.NapCatCore,
      arg0.instance?.core,
      nestedCtx?.instance?.core,
      arg0.instance,
      nestedCtx?.instance
    );
    const obContext = pickFirstDefined(
      arg0.obContext,
      nestedCtx?.obContext,
      arg0.oneBot,
      nestedCtx?.oneBot,
      arg0._ctx?.obContext,
      arg0._ctx?.oneBot,
      arg0.ctx?.obContext,
      arg0.ctx?.oneBot
    );
    const actions = pickFirstDefined(
      arg0.actions,
      nestedCtx?.actions,
      obContext?.actions,
      arg0.instance?.actions,
      nestedCtx?.instance?.actions
    );
    const instance = pickFirstDefined(
      arg0.instance,
      nestedCtx?.instance,
      core
    );

    return {
      core,
      obContext,
      actions,
      instance,
      ctx: arg0,
      nestedCtx
    };
  }

  return {
    core: arg0,
    obContext: arg1,
    actions: arg2,
    instance: arg3,
    ctx: undefined,
    nestedCtx: undefined
  };
}

export async function plugin_init(arg0, arg1, arg2, arg3) {
  try {
    const {
      core,
      obContext,
      actions: rawActions,
      instance,
      ctx,
      nestedCtx
    } = normalizePluginArgs(arg0, arg1, arg2, arg3);

    // 保存 logger 引用，确保日志能正确输出到 NapCat 日志系统
    if (core?.context?.logger) {
      pluginLogger = core.context.logger;
    }
    pluginLogger.log('[QCE] ========== plugin_init CALLED ==========');

    const actions = rawActions || obContext?.actions || instance?.actions || ctx?.actions || nestedCtx?.actions;
    if (!core) {
      throw new Error('NapCat core is missing in plugin_init context');
    }

    const workingEnv = detectWorkingEnv(core);

    // Keep the raw NapCat bridge for overlay API adapters.
    globalThis.__NAPCAT_BRIDGE__ = {
      core,
      obContext,
      actions,
      instance,
      ctx,
      pluginContext: ctx,
      workingEnv
    };

    console.log(
      `[QCE] Running mode: ${
        workingEnv === 'framework'
          ? 'Framework (QQNT plugin)'
          : workingEnv === 'shell'
            ? 'Shell (headless)'
            : 'unknown'
      }`
    );

    const { QQChatExporterApiLauncher } = await import('./runtime/ApiLauncher.mjs');

    const runtimeCore = createFallbackCore(core);
    const realApis = globalThis.__NAPCAT_BRIDGE__?.core?.apis || runtimeCore.apis;
    runtimeCore.apis = createApiAdapter(realApis);

    if (apiLauncher) {
      await apiLauncher.stopApiServer();
      apiLauncher = null;
    }
    apiLauncher = new QQChatExporterApiLauncher(runtimeCore);
    await apiLauncher.startApiServer();
    ingestReady = true;
  } catch (error) {
    console.error('[QCE] Initialization failed:', error);
    console.error(error?.stack || error);
  }
}

export async function plugin_cleanup() {
  try {
    ingestReady = false;
    accessToken = null;
    if (apiLauncher) {
      await apiLauncher.stopApiServer();
      apiLauncher = null;
    }
    delete globalThis.__NAPCAT_BRIDGE__;
  } catch (error) {
    console.error('[QCE] Cleanup failed:', error);
  }
}

/**
 * 把 NapCat 派发的消息事件归一化为原始消息结构。
 * 优先取 `event.raw`（NT 原始消息，需要 NapCat onebot `debug:true`）；
 * 否则从 OneBot 11 消息数组中提取元素，保留所有消息类型（包括语音）。
 */
function normalizeLiveMessage(event) {
  if (event && typeof event === 'object' && event.raw && typeof event.raw === 'object') {
    return event.raw;
  }
  if (event && typeof event === 'object' && (event.message_type || event.message_id)) {
    const isGroup = event.message_type === 'group';
    // 如果有 message 数组（OB11 格式），保留所有元素
    let elements = [];
    if (Array.isArray(event.message)) {
      for (const msg of event.message) {
        if (!msg || typeof msg !== 'object') continue;
        const type = msg.type;
        const data = msg.data || {};

        if (type === 'text') {
          elements.push({ elementType: 1, textElement: { content: data.text ?? '' } });
        } else if (type === 'record' || type === 'voice') {
          // 语音元素 - 记录 OB11 格式的路径信息
          elements.push({
            elementType: 4,
            pttElement: {
              filePath: data.path || data.file || '',
              fileName: data.file || '',
              fileSize: data.file_size || 0,
              // 标记为 OB11 格式，便于后续处理
              _ob11Format: true
            }
          });
        } else if (type === 'image') {
          elements.push({ elementType: 2, imageElement: { file: data.file, url: data.url } });
        } else if (type === 'file') {
          elements.push({ elementType: 23, fileElement: { filePath: data.path || data.file, fileName: data.name || data.file } });
        } else if (type === 'video') {
          elements.push({ elementType: 5, videoElement: { filePath: data.path || data.file, fileName: data.file } });
        } else if (type === 'at') {
          elements.push({ elementType: 3, atElement: { atType: data.qq === 'all' ? 1 : 0, atUin: data.qq } });
        } else if (type === 'reply') {
          elements.push({ elementType: 7, replyElement: { msgId: data.id } });
        } else if (type === 'face') {
          elements.push({ elementType: 6, faceElement: { faceIndex: data.id } });
        }
        // 其他类型暂时保留原始数据
      }
    }

    // 如果没有提取到任何元素，使用原始文本消息
    if (elements.length === 0) {
      elements = [{ elementType: 1, textElement: { content: event.raw_message ?? '' } }];
    }

    return {
      msgId: String(event.message_id ?? ''),
      msgSeq: String(event.message_seq ?? ''),
      msgTime: String(Math.floor(Number(event.time ?? 0))),
      chatType: isGroup ? 2 : 1,
      peerUid: String(isGroup ? (event.group_id ?? '') : (event.user_id ?? '')),
      peerUin: String(event.user_id ?? ''),
      senderUid: '',
      senderUin: String(event.sender?.user_id ?? ''),
      sendNickName: event.sender?.nickname ?? '',
      elements
    };
  }
  return null;
}

async function resolveAccessToken() {
  if (accessToken) return accessToken;
  const { readAccessTokenWithRetry, resolveSecurityConfigPath } = await import('./runtime/rustBridge.mjs');
  const token = await readAccessTokenWithRetry(resolveSecurityConfigPath());
  if (typeof token === 'string' && token.length > 0) {
    accessToken = token;
  }
  return accessToken;
}

export async function plugin_onmessage(ctx, event) {
  try {
    if (!ingestReady) return;
    const raw = normalizeLiveMessage(event);
    if (!raw) return;

    // 消息正常上报到 Rust 后端（包括音频元素，QCCA 需要读取 JSONL 中的音频条目）

    const body = JSON.stringify(raw);
    const qccaResponse = await fetch(`http://127.0.0.1:${QCCA_PORT}/qcca/live-capture/ingest`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body
    });
    if (qccaResponse.ok) return;

    // QCCA 尚未启动时回退到原 QCE 实时捕获接口，避免启动阶段丢消息。
    const token = await resolveAccessToken();
    if (!token) return;
    await fetch(`http://127.0.0.1:${INGEST_PORT}/api/live-capture/ingest`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`
      },
      body
    });
  } catch (error) {
    console.warn('[QCE] live-capture ingest failed:', error?.message || error);
  }
}
