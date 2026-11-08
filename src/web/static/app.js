let eventSource = null;

async function sendQuery() {
    const input = document.getElementById('query-input');
    const btn = document.getElementById('send-btn');
    const question = input.value.trim();
    if (!question) return;

    btn.disabled = true;
    btn.textContent = '查询中...';
    document.getElementById('process-log').innerHTML = '';
    document.getElementById('answer').innerHTML = '';

    try {
        const resp = await fetch('/api/query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({question}),
        });
        const data = await resp.json();
        const answer = document.getElementById('answer');
        answer.innerHTML = renderMarkdown(data.answer || 'No answer');
        if (data.process) {
            data.process.forEach(entry => addLog(entry));
        }
    } catch (e) {
        document.getElementById('answer').textContent = '查询失败: ' + e.message;
    } finally {
        btn.disabled = false;
        btn.textContent = '发送查询';
    }
}

function addLog(text) {
    const log = document.getElementById('process-log');
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    const time = new Date().toLocaleTimeString();
    entry.textContent = `[${time}] ${text}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

// ---------------------------------------------------------------- rendering
function escapeHtml(text) {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function renderInline(text) {
    return text
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
                 '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

// A deliberately small Markdown subset: headings, lists, quotes, rules, bold, links.
function renderMarkdown(markdown) {
    const lines = markdown.split('\n');
    const html = [];
    let inList = false;

    const closeList = () => {
        if (inList) { html.push('</ul>'); inList = false; }
    };

    for (const rawLine of lines) {
        const line = rawLine.trimEnd();
        if (!line.trim()) { closeList(); continue; }

        if (line.startsWith('### ')) {
            closeList();
            html.push(`<h4>${renderInline(escapeHtml(line.slice(4)))}</h4>`);
        } else if (line.startsWith('---')) {
            closeList();
            html.push('<hr>');
        } else if (line.startsWith('> ')) {
            closeList();
            html.push(`<blockquote>${renderInline(escapeHtml(line.slice(2)))}</blockquote>`);
        } else if (line.startsWith('- ')) {
            if (!inList) { html.push('<ul>'); inList = true; }
            html.push(`<li>${renderInline(escapeHtml(line.slice(2)))}</li>`);
        } else {
            closeList();
            html.push(`<p>${renderInline(escapeHtml(line))}</p>`);
        }
    }
    closeList();
    return html.join('');
}

// ---------------------------------------------------------------- agents
function loadAgentStatus() {
    fetch('/api/agents')
        .then(r => r.json())
        .then(agents => {
            const bar = document.getElementById('agent-status');
            bar.innerHTML = '';
            if (agents.length === 0) {
                bar.innerHTML = '<span class="agent-status agent-offline">未发现 Agent</span>';
                return;
            }
            agents.forEach(a => {
                const span = document.createElement('span');
                span.className = 'agent-status ' + (a.enabled ? 'agent-online' : 'agent-disabled');
                span.textContent = a.name + (a.enabled ? '' : ' (已禁用)');
                span.title = (a.description || '') + '\n点击切换启用/禁用';
                span.onclick = () => toggleAgent(a.name, a.enabled);
                bar.appendChild(span);
            });
        });
}

async function toggleAgent(name, currentlyEnabled) {
    const action = currentlyEnabled ? 'disable' : 'enable';
    try {
        await fetch(`/api/agents/${name}/${action}`, { method: 'POST' });
        loadAgentStatus();
    } catch (e) {
        alert('操作失败: ' + e.message);
    }
}

window.addEventListener('load', () => {
    loadAgentStatus();
    // Shareable demo link: /?q=<question> auto-runs the query.
    const q = new URLSearchParams(window.location.search).get('q');
    if (q) {
        document.getElementById('query-input').value = q;
        sendQuery();
    }
});
