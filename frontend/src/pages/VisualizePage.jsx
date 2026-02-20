import React, { useState, useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import { api } from '../api/client';
import { LoadingSpinner, ErrorAlert, StatCard } from '../components/SharedComponents';

const VisualizePage = () => {
    const [graphData, setGraphData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selectedNode, setSelectedNode] = useState(null);
    const [selectedEdge, setSelectedEdge] = useState(null);
    const [moveNeighbors, _setMoveNeighbors] = useState(false);
    const moveNeighborsRef = useRef(false);

    const setMoveNeighbors = (val) => {
        _setMoveNeighbors(val);
        moveNeighborsRef.current = val;
    };
    const [nadiaOpen, setNadiaOpen] = useState(false);
    const [jobId, setJobId] = useState(null);
    const [chatMessages, setChatMessages] = useState([
        { role: 'assistant', content: 'Olá! Eu sou a Nadia. Como posso ajudar você a explorar este grafo hoje?' }
    ]);
    const [isThinking, setIsThinking] = useState(false);
    const [inputMessage, setInputMessage] = useState('');
    const [isAudioEnabled, setIsAudioEnabled] = useState(false);
    const [isSpeaking, setIsSpeaking] = useState(false);
    const [isNadiaStopping, setIsNadiaStopping] = useState(false);
    const stopRef = useRef(false);
    const premiumAudioRef = useRef(null);
    const [sessionCost, setSessionCost] = useState(0);
    const voiceMode = 'none';
    const [usageStats, setUsageStats] = useState({ total_usd: 0, estimated_savings_usd: 0, messages_count: 0 });
    const [searchTerm, setSearchTerm] = useState('');

    const refreshUsage = async () => {
        try {
            const stats = await api.getNadiaUsage();
            setUsageStats(stats);
        } catch (e) {
            console.warn("Failed to fetch usage stats:", e);
        }
    };

    const handleSearch = (term) => {
        setSearchTerm(term);
        if (!cyRef.current) return;
        const cy = cyRef.current;

        if (!term.trim()) {
            cy.elements().removeClass('dimmed highlighted');
            return;
        }

        const matches = cy.nodes().filter(n => {
            if (n.data('isParent')) return false;
            const label = (n.data('label') || '').toLowerCase();
            const type = (n.data('type') || '').toLowerCase();
            return label.includes(term.toLowerCase()) || type.includes(term.toLowerCase());
        });

        cy.elements().addClass('dimmed').removeClass('highlighted');
        matches.addClass('highlighted').removeClass('dimmed');

        if (matches.length > 0) {
            cy.animate({
                center: { eles: matches },
                zoom: 1.2,
                duration: 500
            });
        }
    };

    useEffect(() => {
        refreshUsage();
    }, []);

    const [chatSize, setChatSize] = useState({ width: 384, height: 500 });
    const [isResizing, setIsResizing] = useState(false);

    // Lazy load ReactMarkdown
    const [ReactMarkdown, setReactMarkdown] = useState(null);
    useEffect(() => {
        import('react-markdown').then(mod => setReactMarkdown(() => mod.default)).catch(() => { });
    }, []);

    const cyRef = useRef(null);
    const containerRef = useRef(null);

    const getNodeColor = (type) => {
        if (!type || type === 'Default' || type === 'DESCONHECIDO') return '#94a3b8';

        const palette = [
            '#4f46e5', '#10b981', '#f43f5e', '#f59e0b', '#06b6d4',
            '#8b5cf6', '#ec4899', '#0ea5e9', '#14b8a6', '#f97316',
            '#ef4444', '#84cc16', '#06b6d4', '#d946ef', '#6366f1'
        ];

        const normalized = type.trim().toUpperCase();
        let hash = 0;
        for (let i = 0; i < normalized.length; i++) {
            hash = normalized.charCodeAt(i) + ((hash << 5) - hash);
        }

        return palette[Math.abs(hash) % palette.length];
    };

    const initializeCytoscape = (graphElements, stats) => {
        if (!containerRef.current || !graphElements) return;

        if (cyRef.current) {
            cyRef.current.destroy();
            cyRef.current = null;
        }

        const cy = cytoscape({
            container: containerRef.current,
            elements: graphElements.elements || graphElements,
            style: [
                {
                    selector: 'node:not(.type-parent)',
                    style: {
                        'background-color': (ele) => getNodeColor(ele.data('type')),
                        'label': 'data(label)',
                        'width': (ele) => Math.max(45, Math.min(130, 35 + (ele.data('degree') || 1) * 10)),
                        'height': (ele) => Math.max(45, Math.min(130, 35 + (ele.data('degree') || 1) * 10)),
                        'color': '#ffffff',
                        'text-outline-color': (ele) => getNodeColor(ele.data('type')),
                        'text-outline-width': 3,
                        'font-family': 'Inter, sans-serif',
                        'font-size': '12px',
                        'font-weight': '700',
                        'text-valign': 'center',
                        'text-halign': 'center',
                        'z-index': 10
                    }
                },
                {
                    selector: 'edge',
                    style: {
                        'width': 3,
                        'line-color': '#e2e8f0',
                        'target-arrow-shape': 'triangle',
                        'curve-style': 'bezier',
                        'label': 'data(relation)',
                        'font-size': '10px',
                        'color': '#64748b',
                        'opacity': 0.6,
                        'text-background-opacity': 1,
                        'text-background-color': '#ffffff',
                        'text-background-padding': '2px',
                        'text-background-shape': 'round-rectangle'
                    }
                },
                {
                    selector: '.type-parent',
                    style: {
                        'background-color': '#f8fafc',
                        'background-opacity': 0.7,
                        'border-width': 1.5,
                        'border-color': '#cbd5e1',
                        'border-style': 'dashed',
                        'label': 'data(label)',
                        'text-valign': 'top',
                        'text-halign': 'center',
                        'text-margin-y': -15,
                        'color': '#64748b',
                        'font-size': '16px',
                        'font-weight': '800',
                        'text-transform': 'uppercase',
                        'letter-spacing': '0.1em',
                        'padding': 60,
                        'shape': 'round-rectangle',
                        'z-index': -1,
                        'text-outline-width': 0
                    }
                },
                {
                    selector: '.highlighted',
                    style: { 'border-width': 8, 'border-color': '#fbbf24', 'opacity': 1, 'z-index': 100 }
                },
                {
                    selector: '.dimmed',
                    style: { 'opacity': 0.15, 'text-opacity': 0 }
                }
            ],
            layout: {
                name: 'cose',
                animate: true,
                animationDuration: 1000,
                nodeRepulsion: 15000,
                idealEdgeLength: 150
            }
        });

        cy.on('tap', 'node', (evt) => {
            if (evt.target.data('isParent')) return;
            setSelectedNode(evt.target.data());
            cy.elements().removeClass('highlighted dimmed');
            evt.target.addClass('highlighted');
            evt.target.neighborhood().addClass('highlighted');
            cy.elements().not(evt.target.neighborhood().union(evt.target)).addClass('dimmed');
        });

        cy.on('tap', (evt) => {
            if (evt.target === cy) {
                setSelectedNode(null);
                setSelectedEdge(null);
                cy.elements().removeClass('highlighted dimmed');
            }
        });

        let dragOffsets = new Map();
        cy.on('grab', 'node', (evt) => {
            if (!moveNeighborsRef.current || evt.target.data('isParent')) return;
            const node = evt.target;
            const neighbors = node.neighborhood().nodes();
            const nodePos = node.position();
            neighbors.forEach(n => {
                const nPos = n.position();
                dragOffsets.set(n.id(), { x: nPos.x - nodePos.x, y: nPos.y - nodePos.y });
            });
        });

        cy.on('drag', 'node', (evt) => {
            if (!moveNeighborsRef.current || evt.target.data('isParent')) return;
            const node = evt.target;
            const nodePos = node.position();
            const neighbors = node.neighborhood().nodes();
            neighbors.forEach(n => {
                const offset = dragOffsets.get(n.id());
                if (offset) n.position({ x: nodePos.x + offset.x, y: nodePos.y + offset.y });
            });
        });

        cy.on('free', 'node', () => dragOffsets.clear());

        cyRef.current = cy;
    };
    const chatRef = useRef(null);

    const startResizing = (e) => {
        e.preventDefault();
        setIsResizing(true);
    };

    useEffect(() => {
        const handleMouseMove = (e) => {
            if (!isResizing) return;
            const newWidth = Math.max(300, window.innerWidth - e.clientX - 24);
            const newHeight = Math.max(300, window.innerHeight - e.clientY - 24);
            setChatSize({ width: newWidth, height: newHeight });
        };
        const handleMouseUp = () => setIsResizing(false);

        if (isResizing) {
            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
        }
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isResizing]);

    const cleanTextForSpeech = (text) => {
        return text
            .replace(/\*\*/g, '')
            .replace(/\*/g, '')
            .replace(/#/g, '')
            .replace(/`/g, '')
            .replace(/\[.*?\]\(.*?\)/g, '')
            .replace(/\{.*?\}/g, '')
            .replace(/\n+/g, ' ')
            .trim();
    };

    useEffect(() => {
        return () => {
            if (cyRef.current) cyRef.current.destroy();
            if (window.speechSynthesis) window.speechSynthesis.cancel();
            if (premiumAudioRef.current) premiumAudioRef.current.pause();
        };
    }, []);

    const handleStopNadia = () => {
        stopRef.current = true;
        setIsNadiaStopping(true);
        setIsSpeaking(false);
        setIsThinking(false);
        if (window.speechSynthesis) window.speechSynthesis.cancel();
        if (premiumAudioRef.current) {
            premiumAudioRef.current.pause();
            premiumAudioRef.current = null;
        }
    };

    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        const jid = params.get('job');
        if (jid) {
            setJobId(jid);
            loadGraph(jid);
        } else {
            setLoading(false);
        }
    }, []);

    const handleFileUpload = (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (evt) => {
            try {
                const data = JSON.parse(evt.target.result);
                let processedData;
                if (data.results && data.results.cytoscape) {
                    processedData = { graph: data.results.cytoscape, stats: data.results.graph_stats || {} };
                } else if (data.graph) {
                    processedData = data;
                } else {
                    processedData = { graph: data.elements ? data : { elements: data }, stats: data.stats || {} };
                }
                setGraphData(processedData);
                setError(null);
                setTimeout(() => initializeCytoscape(processedData.graph, processedData.stats), 100);
            } catch (err) {
                setError('Arquivo JSON inválido: ' + err.message);
            }
        };
        reader.readAsText(file);
    };

    const loadGraph = async (jid) => {
        try {
            setLoading(true);
            setJobId(jid);
            const data = await api.getGraph(jid);
            setGraphData(data);
            localStorage.setItem('lastJobId', jid);
            setError(null);
            if (data && data.graph) {
                setTimeout(() => initializeCytoscape(data.graph, data.stats), 200);
            }
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const changeLayout = (layoutName) => {
        if (!cyRef.current) return;
        const cy = cyRef.current;

        // Cleanup any grouping artifacts
        cy.remove('.type-parent');
        cy.nodes().data('parent', null);

        if (layoutName === 'typeGroup') {
            try {
                // Determine distinct types for grouping
                const types = [...new Set(cy.nodes().map(n => n.data('type') || 'OUTROS'))];

                // Use concentric circles to group same colors together stably
                cy.layout({
                    name: 'concentric',
                    concentric: (node) => types.indexOf(node.data('type') || 'OUTROS'),
                    levelWidth: () => 1,
                    padding: 80,
                    animate: true,
                    animationDuration: 1000,
                    spacingFactor: 1.5,
                    stop: () => cy.fit(cy.elements(), 80)
                }).run();
            } catch (err) {
                console.error("Layout Error:", err);
                setError("Erro ao processar agrupamento.");
            }
        } else {
            const layouts = {
                cose: {
                    name: 'cose',
                    animate: true,
                    nodeRepulsion: 12000,
                    idealEdgeLength: 140,
                    randomize: false
                },
                circle: { name: 'circle', animate: true, padding: 50 },
                grid: { name: 'grid', animate: true, padding: 50 },
                breadthfirst: { name: 'breadthfirst', animate: true, directed: true, padding: 50 },
                readingGuide: {
                    name: 'breadthfirst',
                    animate: true,
                    directed: true,
                    padding: 100,
                    spacingFactor: 1.75,
                    roots: cy.nodes().filter(n => n.indegree() === 0).length > 0
                        ? cy.nodes().filter(n => n.indegree() === 0)
                        : cy.nodes().sort((a, b) => b.degree() - a.degree()).slice(0, 1)
                }
            };
            cy.layout(layouts[layoutName] || layouts.cose).run();
        }
    };

    const fitGraph = () => cyRef.current?.fit(null, 80);
    const exportPNG = () => {
        if (!cyRef.current) return;
        const png = cyRef.current.png({ full: true, scale: 3, bg: '#f8fafc' });
        const link = document.createElement('a');
        link.href = png;
        link.download = 'conhecimento-grafo.png';
        link.click();
    };

    const executeNadiaCommand = (cmd) => {
        if (!cyRef.current || !cmd) return;
        try {
            cyRef.current.elements().removeClass('pulsing highlighted').addClass('dimmed');
            if (cmd.action === 'focus_node' && cmd.node_id) {
                const cleanId = String(cmd.node_id).replace(/^ID:\s*/i, '').trim();
                const node = cyRef.current.getElementById(cleanId);
                if (node.length > 0) {
                    node.removeClass('dimmed');
                    cyRef.current.animate({ center: { eles: node }, zoom: 1.2 }, { duration: 1200 });
                    node.addClass('highlighted');
                    node.trigger('tap');
                }
            } else if (cmd.action === 'focus_edge' && cmd.source && cmd.target) {
                const edge = cyRef.current.edges().filter(e =>
                    (e.data('source') === cmd.source && e.data('target') === cmd.target) ||
                    (e.data('source') === cmd.target && e.data('target') === cmd.source)
                );
                if (edge.length > 0) {
                    edge.removeClass('dimmed');
                    edge.source().removeClass('dimmed');
                    edge.target().removeClass('dimmed');
                    cyRef.current.animate({ center: { eles: edge }, zoom: 1.1 }, { duration: 1200 });
                    edge.addClass('highlighted');
                }
            }
        } catch (err) {
            console.error('Nadia Command Error:', err);
        }
    };

    const handleSendMessage = async () => {
        if (!inputMessage.trim() || isThinking) return;
        const userMsg = { role: 'user', content: inputMessage };
        setChatMessages(prev => [...prev, userMsg]);
        setInputMessage('');
        setIsThinking(true);
        setIsNadiaStopping(false);
        stopRef.current = false;
        try {
            const response = await api.nadiaChat(jobId, [...chatMessages, userMsg], graphData, voiceMode);
            if (response.cost_usd) {
                setSessionCost(prev => prev + response.cost_usd);
                refreshUsage();
            }
            const answer = response.answer || "";
            const audio_base64 = response.audio_base64;
            if (audio_base64 && isAudioEnabled) {
                const audioBlob = await (await fetch(`data:audio/wav;base64,${audio_base64}`)).blob();
                const audioUrl = URL.createObjectURL(audioBlob);
                const pAudio = new Audio(audioUrl);
                premiumAudioRef.current = pAudio;
                pAudio.play().catch(e => console.warn("Audio blocked:", e));
                setIsSpeaking(true);
                pAudio.onended = () => { setIsSpeaking(false); premiumAudioRef.current = null; };
            }
            const jsonRegex = /\{\s*"action"\s*:\s*"[^"]+"[^}]*\}/g;
            let cleanedAnswer = answer.replace(jsonRegex, '').replace(/```json/gi, '').replace(/```/g, '').replace(/json/gi, '').replace(/\s*[\(\[]ID:\s*[^\]\)]+[\)\]]/gi, '').replace(/\s+/g, ' ').trim();
            setChatMessages(prev => [...prev, { role: 'assistant', content: cleanedAnswer }]);
            let enrichedAnswer = answer;
            const existingIds = (answer.match(/"node_id":\s*"([^"]+)"/g) || []).map(m => m.match(/"node_id":\s*"([^"]+)"/)[1]);
            const nodesForMatching = graphData?.graph?.elements?.nodes || [];
            const sortedNodes = [...nodesForMatching].sort((a, b) => (b.data.label || "").length - (a.data.label || "").length);
            for (const node of sortedNodes.slice(0, 300)) {
                const label = node.data.label;
                const nid = node.data.id;
                if (label && label.length > 3 && !existingIds.includes(nid)) {
                    const escapedLabel = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const regex = new RegExp(`(^|\\s|["'\\(])(${escapedLabel})(?=[\\s\\.,!\\?\\)"']|$)`, 'i');
                    if (enrichedAnswer.match(regex)) enrichedAnswer = enrichedAnswer.replace(regex, `$1$2 {"action": "focus_node", "node_id": "${nid}"}`);
                }
            }
            const stages = [];
            const textSegments = enrichedAnswer.split(jsonRegex);
            const jsonMatches = enrichedAnswer.match(jsonRegex) || [];
            for (let i = 0; i < textSegments.length; i++) {
                let segment = textSegments[i].replace(/```json/gi, '').replace(/```/g, '').replace(/\bjson\b/gi, '').replace(/\s+/g, ' ').trim();
                const nextCommand = jsonMatches[i] ? JSON.parse(jsonMatches[i]) : null;
                if (segment.length > 0) {
                    const sentences = segment.split(/([.!?](?:\s+|$))/);
                    let tempText = "";
                    for (let s = 0; s < sentences.length; s++) {
                        tempText += sentences[s];
                        if (sentences[s].match(/[.!?]/) || s === sentences.length - 1) {
                            if (tempText.trim()) {
                                const isLastSentence = (s === sentences.length - 1 || (s === sentences.length - 2 && sentences[s + 1].trim() === ""));
                                stages.push({ text: tempText.trim(), command: isLastSentence ? nextCommand : null });
                                tempText = "";
                            }
                        }
                    }
                } else if (nextCommand) stages.push({ text: "", command: nextCommand });
            }
            const finalStages = stages.filter(s => s.text.length > 0 || s.command);
            const startNarrative = async () => {
                for (const stage of finalStages) {
                    if (stopRef.current) break;
                    if (stage.command) executeNadiaCommand(stage.command);
                    await new Promise(r => setTimeout(r, 2800));
                }
            };
            startNarrative().finally(() => { setIsNadiaStopping(false); stopRef.current = false; });
        } catch (err) {
            console.error("Nadia Error:", err);
            setChatMessages(prev => [...prev, { role: 'assistant', content: `Erro: ${err.message}` }]);
        } finally { setIsThinking(false); }
    };

    if (!graphData && !loading) {
        return (
            <div className="max-w-4xl mx-auto px-6 py-20 text-center">
                <div className="bg-white p-12 rounded-[40px] shadow-premium border border-slate-100">
                    <div className="w-20 h-20 bg-brand-primary/10 text-brand-primary rounded-3xl flex items-center justify-center text-3xl mx-auto mb-6">🏜️</div>
                    <h2 className="text-2xl font-display font-bold text-brand-surface mb-2">Sem Grafo Ativo</h2>
                    <p className="text-brand-muted mb-8">Não encontramos um processamento ativo. Inicie um upload ou carregue um JSON.</p>
                    <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                        <a href="/upload" className="px-8 py-4 bg-slate-100 text-slate-700 rounded-2xl font-bold hover:bg-slate-200">Ir para Upload</a>
                        <label className="px-8 py-4 bg-brand-primary text-white rounded-2xl font-bold cursor-pointer shadow-lg">
                            Carregar JSON
                            <input type="file" accept=".json" onChange={handleFileUpload} className="hidden" />
                        </label>
                    </div>
                </div>
            </div>
        );
    }

    if (loading) return (
        <div className="flex flex-col items-center justify-center h-screen bg-seade-gray-light">
            <LoadingSpinner size="lg" />
            <p className="mt-4 text-brand-muted font-medium animate-pulse">Carregando mapa mental...</p>
        </div>
    );

    return (
        <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-white">
            <aside className="w-85 border-r border-gray-100 bg-white/80 backdrop-blur-xl z-10 flex flex-col shadow-2xl">
                <div className="p-6 overflow-y-auto flex-1 custom-scrollbar">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="text-2xl font-display font-bold text-brand-surface tracking-tight">Explorador</h2>
                    </div>
                    <div className="relative mb-8">
                        <input type="text" placeholder="Pesquisar..." value={searchTerm} onChange={(e) => handleSearch(e.target.value)} className="w-full pl-10 pr-4 py-3 bg-slate-50 border border-slate-200 rounded-2xl text-xs outline-none" />
                    </div>
                    <ErrorAlert message={error} onDismiss={() => setError(null)} />
                    {graphData?.stats && (
                        <div className="space-y-6 mb-8">
                            <div className="grid grid-cols-2 gap-3">
                                <StatCard label="Densidade" value={graphData.stats.density.toFixed(3)} />
                                <StatCard label="Grau Médio" value={graphData.stats.avg_degree.toFixed(2)} />
                            </div>
                        </div>
                    )}
                    <div className="space-y-8">
                        <section>
                            <h3 className="text-[11px] font-black text-slate-500 uppercase tracking-widest mb-4">Algoritmo de Layout</h3>
                            <div className="grid grid-cols-2 gap-2">
                                {['cose', 'readingGuide', 'typeGroup', 'circle', 'grid', 'breadthfirst'].map((id) => (
                                    <button key={id} onClick={() => changeLayout(id)} className="px-4 py-3 bg-white border border-slate-200 rounded-2xl text-[11px] font-bold hover:border-brand-primary hover:text-brand-primary transition-all">
                                        {id === 'typeGroup' ? 'Agrupar por Tipo' : id}
                                    </button>
                                ))}
                            </div>
                        </section>
                        <section>
                            <h3 className="text-[11px] font-black text-slate-500 uppercase tracking-widest mb-4">Mapeamento de Tipos</h3>
                            <div className="space-y-1.5">
                                {graphData?.stats?.entity_types && Object.entries(graphData.stats.entity_types).map(([type, count]) => (
                                    <div key={type} className="flex items-center justify-between p-2.5 hover:bg-slate-50 rounded-xl transition-all border border-transparent">
                                        <div className="flex items-center">
                                            <div className="w-3.5 h-3.5 rounded-full mr-3.5" style={{ backgroundColor: getNodeColor(type) }} />
                                            <span className="text-sm font-semibold text-slate-700">{type}</span>
                                        </div>
                                        <span className="text-[11px] font-black text-slate-500">{count}</span>
                                    </div>
                                ))}
                            </div>
                        </section>
                    </div>
                </div>
                <div className="p-6 border-t border-gray-100 grid grid-cols-2 gap-3">
                    <button onClick={fitGraph} className="py-3.5 bg-slate-50 text-slate-700 rounded-2xl text-xs font-black">CENTRALIZAR</button>
                    <button onClick={exportPNG} className="py-3.5 bg-brand-primary text-white rounded-2xl text-xs font-black">EXPORTAR PNG</button>
                </div>
            </aside>
            <main className="flex-1 relative bg-[#f8fafc]">
                <div ref={containerRef} className="w-full h-full" />
                <div className={`absolute bottom-6 right-6 z-50 transition-all ${nadiaOpen ? 'w-96 h-[500px]' : 'w-16 h-16'}`}>
                    {nadiaOpen ? (
                        <div className="w-full h-full bg-white rounded-3xl shadow-2xl border border-slate-100 flex flex-col relative overflow-hidden">
                            <div className="p-4 bg-brand-surface text-white flex justify-between items-center">
                                <span className="font-bold">Agent Nadia</span>
                                <button onClick={() => setNadiaOpen(false)}>✕</button>
                            </div>
                            <div className="flex-1 overflow-y-auto p-5 space-y-4 bg-slate-50">
                                {chatMessages.map((msg, i) => (
                                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                        <div className={`max-w-[85%] p-4 rounded-2xl text-sm ${msg.role === 'user' ? 'bg-brand-primary text-white' : 'bg-white shadow-sm'}`}>
                                            {msg.content}
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <div className="p-4 bg-white border-t border-slate-100 flex space-x-2">
                                <input type="text" value={inputMessage} onChange={(e) => setInputMessage(e.target.value)} placeholder="Pergunte..." className="flex-1 bg-slate-50 border border-slate-200 rounded-2xl px-5 py-3 text-sm outline-none" onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()} />
                                <button onClick={handleSendMessage} className="bg-brand-primary text-white p-3 rounded-2xl">➤</button>
                            </div>
                        </div>
                    ) : (
                        <button onClick={() => setNadiaOpen(true)} className="w-16 h-16 bg-brand-surface text-white rounded-full shadow-2xl flex items-center justify-center">🤖</button>
                    )}
                </div>
            </main>
        </div>
    );
};

export default VisualizePage;
