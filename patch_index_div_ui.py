path = "/var/www/hedge-fund-website/index.html"
text = open(path).read()

old = """            const blocked = (window.buyCandidates || [])
                .filter(c => c.status === 'high_beta_blocked')
                .sort((a, b) => (b.readiness_score || 0) - (a.readiness_score || 0));
            const actionable = queued.length + add.length;
            if (actionable > 0 || blocked.length > 0) {
                html += '<div style="margin-bottom: 14px; padding: 10px 12px; background: rgba(6,182,212,0.08); border: 1px solid rgba(6,182,212,0.2); border-radius: 8px;">';
                html += '<div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Next Buys</div>';
                if (queued.length > 0) {
                    html += '<div style="font-size: 12px; color: #06b6d4; margin-bottom: 4px;">🎯 New buys: ' + queued.map(c => c.symbol).join(', ') + '</div>';
                }
                if (add.length > 0) {
                    html += '<div style="font-size: 12px; color: #fbbf24; margin-bottom: 4px;">➕ Top up holdings: ' + add.map(c => c.symbol).join(', ') + '</div>';
                }
                if (blocked.length > 0) {
                    const blockedReason = blocked[0].reason || 'High-beta basket cap reached';
                    html += '<div style="font-size: 12px; color: #f87171; margin-bottom: 4px;">🛑 Macro cap: ' + blocked.map(c => c.symbol).join(', ') + '</div>';
                    html += '<div style="font-size: 11px; color: var(--text-muted);">' + blockedReason + '</div>';
                }
                html += '</div>';
            }"""

new = """            const blocked = (window.buyCandidates || [])
                .filter(c => c.status === 'high_beta_blocked')
                .sort((a, b) => (b.readiness_score || 0) - (a.readiness_score || 0));
            const div = (window.buyCandidates || [])
                .filter(c => c.status === 'diversification')
                .sort((a, b) => (b.readiness_score || 0) - (a.readiness_score || 0));
            const actionable = queued.length + add.length + div.length;
            if (actionable > 0 || blocked.length > 0) {
                html += '<div style="margin-bottom: 14px; padding: 10px 12px; background: rgba(6,182,212,0.08); border: 1px solid rgba(6,182,212,0.2); border-radius: 8px;">';
                html += '<div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;">Next Buys</div>';
                if (queued.length > 0) {
                    html += '<div style="font-size: 12px; color: #06b6d4; margin-bottom: 4px;">🎯 New buys: ' + queued.map(c => c.symbol).join(', ') + '</div>';
                }
                if (add.length > 0) {
                    html += '<div style="font-size: 12px; color: #fbbf24; margin-bottom: 4px;">➕ Top up holdings: ' + add.map(c => c.symbol).join(', ') + '</div>';
                }
                if (div.length > 0) {
                    html += '<div style="font-size: 12px; color: #a78bfa; margin-bottom: 4px;">🌿 Diversification: ' + div.map(c => c.symbol).join(', ') + '</div>';
                }
                if (blocked.length > 0) {
                    const blockedReason = blocked[0].reason || 'High-beta basket cap reached';
                    html += '<div style="font-size: 12px; color: #f87171; margin-bottom: 4px;">🛑 Macro cap: ' + blocked.map(c => c.symbol).join(', ') + '</div>';
                    html += '<div style="font-size: 11px; color: var(--text-muted);">' + blockedReason + '</div>';
                }
                html += '</div>';
            }"""

if old in text:
    text = text.replace(old, new)
    open(path, "w").write(text)
    print("patched Next Buys UI for diversification")
else:
    print("pattern not found")
