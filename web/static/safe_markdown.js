/**
 * 模型输出的安全子集渲染：先转义全部 HTML，再只恢复加粗 / 换行 / 列表 / http(s) 链接。
 * 浏览器和 Node 单元测试共用这一份实现。
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.CrossfireSafeMarkdown = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function escapeHtml(raw) {
    return String(raw ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeMarkdownHtml(raw) {
    let html = escapeHtml(raw);
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // 只允许 http/https；javascript:、data: 等保持为转义后的纯文本，不生成 <a>。
    html = html.replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>',
    );
    html = html.replace(/(^|\n)- (.+)(?=\n|$)/g, "$1• $2");
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  return { escapeHtml, safeMarkdownHtml };
});
