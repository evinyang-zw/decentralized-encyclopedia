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
        document.getElementById('answer').textContent = data.answer || 'No answer';
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
                span.title = '点击切换启用/禁用';
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

window.addEventListener('load', loadAgentStatus);
