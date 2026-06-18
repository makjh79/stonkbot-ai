        // Render watchlist content - Compact Table Layout
        function renderWatchlistContent() {
            const container = document.getElementById('watchlist-content');
            if (!container) return;
            
            const saved = JSON.parse(localStorage.getItem('aiWatchlistSaved') || '[]');
            aiWatchlist = getWatchlistWithLivePrices();
            
            const sorters = {
                rank: (a, b) => a.rank - b.rank,
                price: (a, b) => b.price - a.price,
                upside: (a, b) => (b.intrinsic - b.price)/b.price - (a.intrinsic - a.price)/a.price,
                rsi: (a, b) => a.rsi - b.rsi,
                aiScore: (a, b) => b.aiScore - a.aiScore
            };
            if (sorters[currentWatchlistSort]) {
                aiWatchlist.sort(sorters[currentWatchlistSort]);
            }
            
            let stocksToShow = showingSavedOnly 
                ? aiWatchlist.filter(s => saved.includes(s.symbol))
                : aiWatchlist;
            
            if (showingSavedOnly && stocksToShow.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: var(--text-muted);">
                        <div style="font-size: 48px; margin-bottom: 16px;">☆</div>
                        <div style="font-size: 16px; margin-bottom: 8px;">No saved stocks yet</div>
                        <div style="font-size: 13px;">Click the star on any stock to save it here</div>
                    </div>
                `;
                return;
            }
            
            let html = `
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <thead>
                            <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                                <th style="text-align: left; padding: 12px 8px; color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Stock</th>
                                <th style="text-align: right; padding: 12px 8px; color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Price</th>
                                <th style="text-align: right; padding: 12px 8px; color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Change</th>
                                <th style="text-align: center; padding: 12px 8px; color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">AI</th>
                                <th style="text-align: center; padding: 12px 8px; color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Signal</th>
                                <th style="text-align: center; padding: 12px 8px; color: var(--text-muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Save</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            stocksToShow.forEach(stock => {
                const isSaved = saved.includes(stock.symbol);
                const aiScoreColor = stock.aiScore >= 90 ? '#22c55e' : stock.aiScore >= 75 ? '#eab308' : '#06b6d4';
                const changeColor = stock.changePct >= 0 ? '#22c55e' : '#ef4444';
                const changeIcon = stock.changePct >= 0 ? '▲' : '▼';
                const signalText = stock.rsi <= 35 ? 'BUY' : stock.rsi <= 45 ? 'WATCH' : 'WAIT';
                const signalColor = stock.rsi <= 35 ? '#22c55e' : stock.rsi <= 45 ? '#fbbf24' : 'var(--text-muted)';
                const isOversold = stock.rsi <= 35;
                
                html += `
                    <tr onclick="showStockChart('${stock.symbol}')" 
                        style="border-bottom: 1px solid rgba(255,255,255,0.04); cursor: pointer; transition: background 0.2s;"
                        onmouseover="this.style.background='rgba(255,255,255,0.03)'" 
                        onmouseout="this.style.background='transparent'">
                        <td style="padding: 14px 8px;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span style="font-family: monospace; font-size: 16px; font-weight: 700;">${stock.symbol}</span>
                                ${isOversold ? '<span style="background: #ef4444; color: white; font-size: 9px; font-weight: 700; padding: 2px 5px; border-radius: 4px;">RSI</span>' : ''}
                            </div>
                            <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">${stock.company}</div>
                        </td>
                        <td style="padding: 14px 8px; text-align: right; font-family: monospace; font-size: 16px; font-weight: 700;">
                            $${stock.price.toFixed(2)}
                        </td>
                        <td style="padding: 14px 8px; text-align: right;">
                            <span style="color: ${changeColor}; font-weight: 600; font-size: 13px;">${changeIcon} ${Math.abs(stock.changePct).toFixed(1)}%</span>
                        </td>
                        <td style="padding: 14px 8px; text-align: center;">
                            <span style="background: ${aiScoreColor}20; color: ${aiScoreColor}; font-size: 13px; font-weight: 700; padding: 4px 10px; border-radius: 12px; border: 1px solid ${aiScoreColor}40;">${stock.aiScore}</span>
                        </td>
                        <td style="padding: 14px 8px; text-align: center;">
                            <span style="color: ${signalColor}; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">${signalText}</span>
                        </td>
                        <td style="padding: 14px 8px; text-align: center;" onclick="event.stopPropagation();">
                            <button onclick="toggleWatchStock('${stock.symbol}')" style="background: none; border: none; font-size: 18px; cursor: pointer; color: ${isSaved ? '#fbbf24' : 'var(--text-muted)'}; padding: 4px;">${isSaved ? '★' : '☆'}</button>
                        </td>
                    </tr>
                `;
            });
            
            html += `
                        </tbody>
                    </table>
                </div>
                <div style="text-align: center; padding: 16px; color: var(--text-muted); font-size: 12px; border-top: 1px solid rgba(255,255,255,0.06); margin-top: 8px;">
                    Tap any row to view detailed chart and analysis
                </div>
            `;
            
            container.innerHTML = html;
        }
