/**
 * QCE Search Enhancer
 * 为设置页面的"实时捕获"会话列表和"安全"IP名单添加搜索过滤功能
 * 通过 MutationObserver 监听 modal 弹出，自动注入搜索框
 */
(function () {
  'use strict';

  // 防止重复注入
  if (window.__qceSearchEnhancer) return;
  window.__qceSearchEnhancer = true;

  // The injected QCCA link; QCE may re-render its sidebar and drop it.
  var navigationEntry = null;

  function injectQccaNavigation() {
    if (navigationEntry && navigationEntry.isConnected) return;
    navigationEntry = document.querySelector('[data-qcca-navigation]');
    if (navigationEntry) return;

    var candidates = document.querySelectorAll('a, button');
    var settingsEntry = null;
    for (var i = 0; i < candidates.length; i++) {
      if ((candidates[i].textContent || '').trim() === '设置') {
        settingsEntry = candidates[i];
        break;
      }
    }
    if (!settingsEntry || !settingsEntry.parentElement) return;

    var entry = document.createElement('a');
    var apiPort = new URLSearchParams(location.search).get('apiPort') || '';
    try { apiPort = apiPort || window.localStorage.getItem('qccaApiPort') || ''; } catch (error) {}
    if (/^\d{1,5}$/.test(apiPort) && Number(apiPort) >= 1 && Number(apiPort) <= 65535) {
      entry.href = '/qce/qcca/?apiPort=' + encodeURIComponent(apiPort);
    } else {
      entry.href = '/qce/qcca/';
    }
    entry.className = settingsEntry.className;
    entry.dataset.qccaNavigation = 'true';
    entry.style.textDecoration = 'none';
    entry.innerHTML = settingsEntry.innerHTML;

    var walker = document.createTreeWalker(entry, NodeFilter.SHOW_TEXT);
    var textNode;
    while ((textNode = walker.nextNode())) {
      if (textNode.nodeValue.trim() === '设置') textNode.nodeValue = textNode.nodeValue.replace('设置', 'QCCA');
    }

    settingsEntry.parentElement.insertBefore(entry, settingsEntry);
    navigationEntry = entry;
  }

  /**
   * 在可滚动列表容器上方注入搜索框
   * @param {HTMLElement} scrollContainer - 包含 checkbox 列表的可滚动容器
   * @param {string} placeholderText - 搜索框占位提示文字
   */
  function injectSearchBox(scrollContainer, placeholderText) {
    // 检查是否已注入
    if (scrollContainer.previousElementSibling && scrollContainer.previousElementSibling.dataset.qceSearch) {
      return;
    }

    // 找到实际的列表项容器（可能是 scrollContainer 本身，也可能是它的第一个子元素）
    var listContainer = scrollContainer;
    if (scrollContainer.children.length === 1 && scrollContainer.children[0].children.length > 10) {
      listContainer = scrollContainer.children[0];
    }

    // 创建搜索框容器
    var searchWrapper = document.createElement('div');
    searchWrapper.dataset.qceSearch = 'true';
    searchWrapper.style.cssText = 'position: relative; margin-bottom: 8px; flex-shrink: 0;';

    var searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.placeholder = placeholderText || '搜索…';
    searchInput.style.cssText = [
      'width: 100%',
      'padding: 8px 12px',
      'border: 1px solid #d1d5db',
      'border-radius: 8px',
      'font-size: 14px',
      'outline: none',
      'background: transparent',
      'color: inherit',
      'transition: border-color 0.15s',
    ].join(';');

    // 深色模式适配
    function updateDarkMode() {
      var isDark = document.documentElement.classList.contains('dark');
      if (isDark) {
        searchInput.style.borderColor = '#374151';
        searchInput.style.background = '#1f2937';
        searchInput.style.color = '#f9fafb';
      } else {
        searchInput.style.borderColor = '#d1d5db';
        searchInput.style.background = 'transparent';
        searchInput.style.color = 'inherit';
      }
    }
    updateDarkMode();

    // 监听深色模式变化；搜索框随对话框关闭后断开，避免每次打开都遗留一个监听器
    var observer = new MutationObserver(function () {
      if (!searchInput.isConnected) {
        observer.disconnect();
        return;
      }
      updateDarkMode();
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

    // 聚焦样式
    searchInput.addEventListener('focus', function () {
      searchInput.style.borderColor = '#3b82f6';
    });
    searchInput.addEventListener('blur', function () {
      var isDark = document.documentElement.classList.contains('dark');
      searchInput.style.borderColor = isDark ? '#374151' : '#d1d5db';
    });

    // 过滤逻辑
    var filterTimer = null;
    searchInput.addEventListener('input', function () {
      var keyword = searchInput.value.trim().toLowerCase();
      if (filterTimer) clearTimeout(filterTimer);
      filterTimer = setTimeout(function () {
        // 获取所有列表项 (label 或 div)
        var items = listContainer.children;
        var visibleCount = 0;
        for (var i = 0; i < items.length; i++) {
          var item = items[i];
          var text = (item.textContent || '').toLowerCase();
          if (keyword === '' || text.indexOf(keyword) !== -1) {
            item.style.display = '';
            visibleCount++;
          } else {
            item.style.display = 'none';
          }
        }
        // 显示/隐藏"无结果"提示
        var noResult = scrollContainer.parentElement.querySelector('[data-qce-no-result]');
        if (visibleCount === 0) {
          if (!noResult) {
            noResult = document.createElement('div');
            noResult.dataset.qceNoResult = 'true';
            noResult.style.cssText = 'text-align: center; padding: 16px; color: #9ca3af; font-size: 14px;';
            noResult.textContent = '没有匹配的会话';
            scrollContainer.parentElement.appendChild(noResult);
          }
          noResult.style.display = '';
        } else {
          if (noResult) noResult.style.display = 'none';
        }
      }, 100);
    });

    searchWrapper.appendChild(searchInput);

    // 插入到滚动容器之前
    scrollContainer.parentElement.insertBefore(searchWrapper, scrollContainer);

    // 自动聚焦
    setTimeout(function () {
      searchInput.focus();
    }, 100);
  }

  /**
   * 查找需要注入搜索框的滚动容器
   * 特征: class 包含 overflow-y-auto 且包含大量子元素
   */
  function findScrollContainer(dialog) {
    var containers = dialog.querySelectorAll('.overflow-y-auto, .overflow-auto');
    for (var i = 0; i < containers.length; i++) {
      var c = containers[i];
      // 直接包含多个子元素
      if (c.children.length > 10) {
        return c;
      }
      // 或者子元素只有1个，但孙元素很多（嵌套列表结构）
      if (c.children.length === 1 && c.children[0].children.length > 10) {
        return c;
      }
    }
    return null;
  }

  /**
   * 按对话框类型返回搜索框占位文字，不需要搜索时返回 null。
   * 优先级：会话选择 > 导出会话 > IP 名单。只读取一次 textContent，
   * 大型会话列表的文本可能很长。
   */
  function dialogPlaceholder(dialog) {
    var text = dialog.textContent || '';
    if (text.indexOf('捕获') !== -1 || text.indexOf('会话') !== -1) return '搜索会话名称或 QQ 号…';
    if (text.indexOf('导出') !== -1) return '搜索要导出的会话…';
    if (text.indexOf('IP') !== -1 || text.indexOf('名单') !== -1 || text.indexOf('地址') !== -1) return '搜索 IP 地址…';
    return null;
  }

  /**
   * 为对话框注入搜索框（如需要）。先做廉价的结构检查，只有确实需要注入时才读取文本。
   */
  function processDialog(dialog) {
    if (!dialog.isConnected) return;
    var scrollContainer = findScrollContainer(dialog);
    if (!scrollContainer) return;
    var previous = scrollContainer.previousElementSibling;
    if (previous && previous.dataset && previous.dataset.qceSearch) return;
    var placeholder = dialogPlaceholder(dialog);
    if (placeholder) injectSearchBox(scrollContainer, placeholder);
  }

  // DOM 变化可能非常频繁（例如列表逐批加载数千项）。把待处理的对话框合并到
  // 下一帧统一处理，每个对话框每帧最多检查一次。
  var pendingDialogs = new Set();
  var dialogFrame = 0;

  function queueDialog(dialog) {
    pendingDialogs.add(dialog);
    if (!dialogFrame) dialogFrame = window.requestAnimationFrame(flushDialogs);
  }

  function flushDialogs() {
    dialogFrame = 0;
    var dialogs = Array.from(pendingDialogs);
    pendingDialogs.clear();
    for (var i = 0; i < dialogs.length; i++) processDialog(dialogs[i]);
  }

  // 找不到“设置”入口时需要扫描页面上所有链接和按钮；限制扫描频率，
  // 并保证最后一次 DOM 变化之后仍会检查一次。
  var navigationTimer = 0;

  function queueNavigationCheck() {
    if (navigationTimer || (navigationEntry && navigationEntry.isConnected)) return;
    navigationTimer = window.setTimeout(function () {
      navigationTimer = 0;
      injectQccaNavigation();
    }, 150);
  }

  /**
   * 处理新出现的 dialog
   */
  function handleDialog(dialog) {
    queueDialog(dialog);
    // 等待 DOM 渲染完成后再检查一次
    setTimeout(function () {
      queueDialog(dialog);
    }, 200);
  }

  // 使用 MutationObserver 监听 DOM 变化
  var bodyObserver = new MutationObserver(function (mutations) {
    for (var i = 0; i < mutations.length; i++) {
      var mutation = mutations[i];
      for (var j = 0; j < mutation.addedNodes.length; j++) {
        var node = mutation.addedNodes[j];
        if (node.nodeType === Node.ELEMENT_NODE) {
          // 检查是否是 modal dialog
          if (node.getAttribute && node.getAttribute('role') === 'dialog') {
            handleDialog(node);
          }
          // 也检查子元素中是否有 dialog
          var dialogs = node.querySelectorAll ? node.querySelectorAll('[role=dialog]') : [];
          for (var k = 0; k < dialogs.length; k++) {
            handleDialog(dialogs[k]);
          }
        }
      }
    }
  });

  // 开始监听 body 的子元素变化
  bodyObserver.observe(document.body, { childList: true, subtree: false });

  // 也监听已有 dialog 的变化（处理 dialog 内容动态加载的情况）
  var existingDialogs = document.querySelectorAll('[role=dialog]');
  for (var i = 0; i < existingDialogs.length; i++) {
    handleDialog(existingDialogs[i]);
  }
  injectQccaNavigation();

  // 额外: 监听 dialog 内部的 DOM 变化（处理异步加载列表的情况）
  var dialogContentObserver = new MutationObserver(function (mutations) {
    queueNavigationCheck();
    var lastTarget = null;
    for (var i = 0; i < mutations.length; i++) {
      var mutation = mutations[i];
      // 同一批次中连续追加到同一容器的记录只需查找一次所属对话框
      if (mutation.addedNodes.length > 0 && mutation.target !== lastTarget) {
        lastTarget = mutation.target;
        var dialog = mutation.target.closest ? mutation.target.closest('[role=dialog]') : null;
        if (dialog) queueDialog(dialog);
      }
    }
  });

  // 监听整个文档的子树变化（用于捕获 dialog 内异步加载的内容）
  dialogContentObserver.observe(document.body, { childList: true, subtree: true });

  console.log('[QCE] Search enhancer loaded');
})();
