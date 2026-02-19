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
    // Voice is disabled — hardcoded to 'none' to avoid local model load
    const voiceMode = 'none';
    const [usageStats, setUsageStats] = useState({ total_usd: 0, estimated_savings_usd: 0, messages_count: 0 });

    const refreshUsage = async () => {
        try {
            const stats = await api.getNadiaUsage();
            setUsageStats(stats);
        } catch (e) {
            console.warn("Failed to fetch usage stats:", e);
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
    const chatRef = useRef(null);

    // Resize handling
    const startResizing = (e) => {
        e.preventDefault();
        setIsResizing(true);
    };

    useEffect(() => {
        const handleMouseMove = (e) => {
            if (!isResizing) return;
            // Subtract size from bottom-right corner logic
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

    // Audio is disabled — no localStorage sync needed

    // TTS Helper
    const cleanTextForSpeech = (text) => {
        return text
            .replace(/\*\*/g, '') // Remove bold
            .replace(/\*/g, '')  // Remove italic/bullet
            .replace(/#/g, '')   // Remove headers
            .replace(/`/g, '')   // Remove inline code
            .replace(/\[.*?\]\(.*?\)/g, '') // Remove links
            .replace(/\{.*?\}/g, '') // Remove JSON blocks
            .replace(/\n+/g, ' ') // Replace newlines with space
            .trim();
    };

    const speak = (text, onEnd = null) => {
        if (!isAudioEnabled || !window.speechSynthesis) {
            if (onEnd) onEnd();
            return;
        }

        // Cancel previous speech
        window.speechSynthesis.cancel();

        const cleanText = cleanTextForSpeech(text);
        if (!cleanText) {
            if (onEnd) onEnd();
            return;
        }

        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.lang = 'pt-BR';
        utterance.rate = 1.0;

        // Force a single, consistent female voice (prevent mixing)
        const voices = window.speechSynthesis.getVoices();

        // Find the first Portuguese female voice and stick with it
        const selectedVoice = voices.find(v =>
            v.lang.startsWith('pt') &&
            (v.name.toLowerCase().includes('female') ||
                v.name.toLowerCase().includes('maria') ||
                v.name.toLowerCase().includes('francisca'))
        ) || voices.find(v => v.lang.startsWith('pt')) || voices[0];

        if (selectedVoice) {
            utterance.voice = selectedVoice;
            console.log('🎙️ Using voice:', selectedVoice.name);
        }

        utterance.onstart = () => setIsSpeaking(true);
        utterance.onend = () => {
            setIsSpeaking(false);
            if (onEnd) onEnd();
        };
        utterance.onerror = () => {
            setIsSpeaking(false);
            if (onEnd) onEnd();
        };

        window.speechSynthesis.speak(utterance);
    };

    const handleStopNadia = () => {
        console.log("🛑 Stopping Nadia...");
        stopRef.current = true;
        setIsNadiaStopping(true);
        setIsSpeaking(false);
        setIsThinking(false);

        // Cancel browser TTS
        if (window.speechSynthesis) {
            window.speechSynthesis.cancel();
        }

        // Stop native GPT-4o audio if playing
        if (premiumAudioRef.current) {
            premiumAudioRef.current.pause();
            premiumAudioRef.current = null;
        }

        // We'll also need to stop any active HTML5 Audio later if applicable
        // The check happens inside startNarrative loop
    };

    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        const jid = params.get('job');

        if (jid) {
            setJobId(jid);
            loadGraph(jid);
        } else {
            // Show upload option instead of error
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
                // The uploaded JSON should match the expected structure: { graph: { elements: ... }, stats: ... }
                // or just the elements if it's a raw Cytoscape export.

                let processedData;

                // Case 1: Full Backend Result JSON (with results.cytoscape)
                if (data.results && data.results.cytoscape) {
                    processedData = {
                        graph: data.results.cytoscape,
                        stats: data.results.graph_stats || {}
                    };
                }
                // Case 2: API Response Format (already processed)
                else if (data.graph) {
                    processedData = data;
                }
                // Case 3: Raw Cytoscape Export or Simple Elements
                else {
                    processedData = {
                        graph: data.elements ? data : { elements: data },
                        stats: data.stats || {}
                    };
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
            const data = await api.getGraph(jid);
            setGraphData(data);
            // Save for other pages like Ontology
            localStorage.setItem('lastJobId', jid);
            setError(null);
            setTimeout(() => initializeCytoscape(data.graph, data.stats), 100);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const initializeCytoscape = (graphElements, stats) => {
        if (!containerRef.current || !graphElements) return;

        // Use stats passed directly to avoid state race conditions in style functions
        const nodeImportance = stats?.node_importance || {};

        const cy = cytoscape({
            container: containerRef.current,
            elements: graphElements.elements,
            style: [
                {
                    selector: 'node',
                    style: {
                        'background-color': (ele) => getNodeColor(ele.data('type'), ele.data('color')),
                        'background-opacity': (ele) => {
                            const imp = nodeImportance[ele.id()] || 0.5;
                            return 0.6 + (imp * 0.4);
                        },
                        'label': 'data(label)',
                        'width': (ele) => {
                            const degree = ele.data('degree') || 1;
                            const imp = nodeImportance[ele.id()] || 0;
                            return Math.max(40, Math.min(130, 35 + degree * 10 + imp * 20));
                        },
                        'height': (ele) => {
                            const degree = ele.data('degree') || 1;
                            const imp = nodeImportance[ele.id()] || 0;
                            return Math.max(40, Math.min(130, 35 + degree * 10 + imp * 20));
                        },
                        'border-width': (ele) => {
                            const imp = nodeImportance[ele.id()] || 0;
                            return imp > 0.7 ? 4 : 0;
                        },
                        'border-color': '#ffffff',
                        'font-family': 'Inter, sans-serif',
                        'font-size': (ele) => {
                            const degree = ele.data('degree') || 1;
                            return Math.max(12, Math.min(18, 10 + degree));
                        },
                        'font-weight': '600',
                        'text-valign': 'center',
                        'text-halign': 'center',
                        'color': '#ffffff',
                        'text-outline-color': (ele) => getNodeColor(ele.data('type'), ele.data('color')),
                        'text-outline-width': 3,
                        'text-outline-opacity': 1,
                        'z-index': 10,
                        'transition-property': 'background-color, width, height, border-width, border-color, background-opacity',
                        'transition-duration': '0.3s',
                        'ghost': 'yes',
                        'ghost-offset-x': 0,
                        'ghost-offset-y': 4,
                        'ghost-opacity': 0.1
                    }
                },
                {
                    selector: 'edge',
                    style: {
                        'width': (ele) => Math.max(2, (ele.data('weight') || 1) * 3),
                        'line-color': '#cbd5e1',
                        'target-arrow-color': '#94a3b8',
                        'target-arrow-shape': 'triangle',
                        'curve-style': 'bezier',
                        'label': 'data(relation)',
                        'font-size': '10px',
                        'font-family': 'Inter, sans-serif',
                        'text-rotation': 'autorotate',
                        'text-margin-y': -12,
                        'color': '#475569',
                        'edge-text-rotation': 'autorotate',
                        'opacity': 0.6,
                        'arrow-scale': 1.2
                    }
                },
                {
                    selector: 'node:selected',
                    style: {
                        'border-width': 6,
                        'border-color': '#ffffff',
                        'border-opacity': 0.8,
                        'background-color': '#000000',
                        'text-outline-color': '#000000'
                    }
                },
                {
                    selector: 'node.highlighted',
                    style: {
                        'z-index': 999,
                        'border-width': 4,
                        'border-color': '#ffd700',
                        'opacity': 1
                    }
                },
                {
                    selector: 'node.dimmed',
                    style: {
                        'opacity': 0.1, // Ghost Mode: Very faint
                        'text-opacity': 0.05,
                        'border-color': '#e2e8f0'
                    }
                },
                {
                    selector: 'edge.highlighted',
                    style: {
                        'line-color': '#6366f1',
                        'target-arrow-color': '#6366f1',
                        'width': 6,
                        'opacity': 1,
                        'z-index': 998
                    }
                },
                {
                    selector: 'node.pulsing',
                    style: {
                        'border-width': 8,
                        'border-color': '#ff4757',
                        'transition-property': 'border-width, border-color',
                        'transition-duration': '0.5s'
                    }
                }
            ],
            layout: {
                name: 'cose',
                animate: true,
                animationDuration: 1200,
                nodeRepulsion: 25000, // Much stronger repulsion
                idealEdgeLength: 280, // Much longer edges
                edgeElasticity: 100,
                nodeOverlap: 20,
                gravity: 0.25,
                numIter: 500,
                initialTemp: 200,
                coolingFactor: 0.95,
                minTemp: 1.0,
                randomize: true
            }
        });

        // Event handlers
        cy.on('tap', 'node', (evt) => {
            const node = evt.target;
            setSelectedNode(node.data());
            setSelectedEdge(null);

            // Highlight neighborhood
            cy.elements().removeClass('highlighted dimmed');
            node.addClass('highlighted');
            node.neighborhood().addClass('highlighted');

            // Dim others
            cy.elements().not(node.neighborhood().union(node)).addClass('dimmed');
        });

        cy.on('tap', 'edge', (evt) => {
            const edge = evt.target;
            setSelectedEdge(edge.data());
            setSelectedNode(null);

            cy.elements().removeClass('highlighted dimmed');
            edge.addClass('highlighted');
            edge.source().addClass('highlighted');
            edge.target().addClass('highlighted');
            cy.elements().not(edge.source().union(edge.target()).union(edge)).addClass('dimmed');
        });

        cy.on('tap', (evt) => {
            if (evt.target === cy) {
                setSelectedNode(null);
                setSelectedEdge(null);
                cy.elements().removeClass('highlighted dimmed');
            }
        });

        // Drag handler for "Move Neighbors"
        let dragOffsets = new Map();

        cy.on('grab', 'node', (evt) => {
            if (!moveNeighborsRef.current) return;
            const node = evt.target;
            const neighbors = node.neighborhood().nodes();
            const nodePos = node.position();

            neighbors.forEach(n => {
                const nPos = n.position();
                dragOffsets.set(n.id(), {
                    x: nPos.x - nodePos.x,
                    y: nPos.y - nodePos.y
                });
            });
        });

        cy.on('drag', 'node', (evt) => {
            if (!moveNeighborsRef.current) return;
            const node = evt.target;
            const nodePos = node.position();
            const neighbors = node.neighborhood().nodes();

            neighbors.forEach(n => {
                const offset = dragOffsets.get(n.id());
                if (offset) {
                    n.position({
                        x: nodePos.x + offset.x,
                        y: nodePos.y + offset.y
                    });
                }
            });
        });

        cy.on('free', 'node', () => {
            dragOffsets.clear();
        });

        cyRef.current = cy;
    };

    const getNodeColor = (type, communityColor) => {
        const colors = {
            'PESSOA': '#6366f1',
            'ORGANIZAÇÃO': '#06b6d4',
            'CONCEITO': '#ec4899',
            'TERMO_TÉCNICO': '#f59e0b',
            'LOCAL': '#10b981',
            'EVENTO/DATA': '#8b5cf6',
            'PROCESSO': '#f43f5e',
            'RESULTADO': '#10b981',
            'INDICADOR': '#0ea5e9',
            'ESTRATÉGIA': '#f59e0b',
            'Default': communityColor || '#94a3b8'
        };
        const normalizedType = type?.toUpperCase() || 'Default';
        return colors[normalizedType] || colors['Default'];
    };

    const changeLayout = (layoutName) => {
        if (!cyRef.current) return;

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
                roots: cyRef.current.nodes().filter(n => n.indegree() === 0).length > 0
                    ? cyRef.current.nodes().filter(n => n.indegree() === 0)
                    : cyRef.current.nodes().sort((a, b) => b.degree() - a.degree()).slice(0, 1)
            }
        };

        cyRef.current.layout(layouts[layoutName] || layouts.cose).run();
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
            // THEATRICAL MODE: Dim everything first 
            cyRef.current.elements().removeClass('pulsing highlighted').addClass('dimmed');

            if (cmd.action === 'focus_node' && cmd.node_id) {
                // Remove common prefixes like "ID: " that the AI might include
                const cleanId = String(cmd.node_id).replace(/^ID:\s*/i, '').trim();
                const node = cyRef.current.getElementById(cleanId);
                if (node.length > 0) {
                    node.removeClass('dimmed');
                    cyRef.current.animate({
                        center: { eles: node },
                        zoom: 1.2
                    }, { duration: 1200 });

                    // Highlight node with pulse
                    node.addClass('pulsing');

                    // Trigger tap for details
                    node.trigger('tap');

                    // Cleanup after delay
                    setTimeout(() => {
                        node.removeClass('pulsing');
                    }, 3000);
                }
            } else if (cmd.action === 'focus_edge' && cmd.source && cmd.target) {
                // Find edge between source and target
                const edge = cyRef.current.edges().filter(e =>
                    (e.data('source') === cmd.source && e.data('target') === cmd.target) ||
                    (e.data('source') === cmd.target && e.data('target') === cmd.source)
                );

                if (edge.length > 0) {
                    edge.removeClass('dimmed');
                    edge.source().removeClass('dimmed');
                    edge.target().removeClass('dimmed');

                    cyRef.current.animate({
                        center: { eles: edge },
                        zoom: 1.1
                    }, { duration: 1200 });

                    edge.addClass('highlighted');
                    edge.source().addClass('pulsing');
                    edge.target().addClass('pulsing');

                    setTimeout(() => {
                        edge.removeClass('highlighted');
                        edge.source().removeClass('pulsing');
                        edge.target().removeClass('pulsing');
                    }, 3500);
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

            // Accumulate financial cost
            if (response.cost_usd) {
                setSessionCost(prev => prev + response.cost_usd);
                refreshUsage(); // Sync with global usage
            }

            const answer = response.answer || "";
            const audio_base64 = response.audio_base64;
            let premiumAudioPresent = false;

            if (audio_base64 && isAudioEnabled) {
                // ALWAYS use the backend-provided audio (whether Premium or Local-Concatenated)
                // This eliminates the 30s stuttering in local mode
                console.log("🔊 Received audio. Model:", response.model_used);
                const audioBlob = await (await fetch(`data:audio/wav;base64,${audio_base64}`)).blob();
                const audioUrl = URL.createObjectURL(audioBlob);
                const pAudio = new Audio(audioUrl);
                premiumAudioRef.current = pAudio;
                premiumAudioPresent = true;

                pAudio.play().catch(e => {
                    console.warn("Premium playback blocked:", e);
                    premiumAudioPresent = false;
                });
                setIsSpeaking(true);

                pAudio.onended = () => {
                    setIsSpeaking(false);
                    premiumAudioRef.current = null;
                };
            }
            const jsonRegex = /\{\s*"action"\s*:\s*"[^"]+"[^}]*\}/g;

            // Aggressive JSON cleaning for the chat UI display
            let cleanedAnswer = answer.replace(jsonRegex, '');
            // Remove markdown code blocks and keywords
            cleanedAnswer = cleanedAnswer.replace(/```json/gi, '').replace(/```/g, '');
            cleanedAnswer = cleanedAnswer.replace(/json/gi, '');
            // Remove visible ID tags like (ID: XXX) or [ID: XXX]
            cleanedAnswer = cleanedAnswer.replace(/\s*[\(\[]ID:\s*[^\]\)]+[\)\]]/gi, '');
            // Clean up extra whitespace
            cleanedAnswer = cleanedAnswer.replace(/\s+/g, ' ').trim();

            // Show message immediately in chat (UI feedback) - CLEANED
            setChatMessages(prev => [...prev, { role: 'assistant', content: cleanedAnswer }]);

            // 2. Build narrative stages for the sequential engine
            const jsonRegexGlobal = /\{\s*"action"\s*:\s*"[^"]+"[^}]*\}/g;

            // --- SMART ENTITY INJECTION (Fallback) ---
            // If the AI didn't provide enough commands, we auto-inject based on entity mentions
            let enrichedAnswer = answer;
            const existingIds = (answer.match(/"node_id":\s*"([^"]+)"/g) || []).map(m => m.match(/"node_id":\s*"([^"]+)"/)[1]);

            const nodesForMatching = graphData?.graph?.elements?.nodes || [];
            // Sort by length longest first to avoid "PIB" matching "PIB Mensal" partially
            const sortedNodes = [...nodesForMatching].sort((a, b) => (b.data.label || "").length - (a.data.label || "").length);

            // Increase limit significantly to catch all entities mentioned
            for (const node of sortedNodes.slice(0, 300)) {
                const label = node.data.label;
                const nid = node.data.id;

                if (label && label.length > 3 && !existingIds.includes(nid)) {
                    // Match entity name even if it's at start/end of sentence or has punctuation
                    const escapedLabel = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    // regex that matches the word even with punctuation around it
                    const regex = new RegExp(`(^|\\s|["'\\(])(${escapedLabel})(?=[\\s\\.,!\\?\\)"']|$)`, 'i');

                    if (enrichedAnswer.match(regex)) {
                        // Inject command right after the first mention
                        // We use $1 and $2 to preserve the prefix (space/start) and the word itself
                        enrichedAnswer = enrichedAnswer.replace(regex, `$1$2 {"action": "focus_node", "node_id": "${nid}"}`);
                    }
                }
            }

            const stages = [];
            // Split the original answer by JSON blocks
            const textSegments = enrichedAnswer.split(jsonRegexGlobal);
            const jsonMatches = enrichedAnswer.match(jsonRegexGlobal) || [];

            for (let i = 0; i < textSegments.length; i++) {
                let segment = textSegments[i];
                // Clean segment from markdown artifacts
                segment = segment.replace(/```json/gi, '').replace(/```/g, '');
                segment = segment.replace(/\bjson\b/gi, '');
                segment = segment.replace(/\s+/g, ' ').trim();

                const nextCommand = jsonMatches[i] ? JSON.parse(jsonMatches[i]) : null;

                // If segment has text, break it into sentences for better pacing
                if (segment.length > 0) {
                    const sentences = segment.split(/([.!?](?:\s+|$))/);
                    let tempText = "";
                    for (let s = 0; s < sentences.length; s++) {
                        tempText += sentences[s];
                        if (sentences[s].match(/[.!?]/) || s === sentences.length - 1) {
                            if (tempText.trim()) {
                                // Only attach the command to the LAST sentence of this segment
                                const isLastSentence = (s === sentences.length - 1 || (s === sentences.length - 2 && sentences[s + 1].trim() === ""));
                                stages.push({
                                    text: tempText.trim(),
                                    command: isLastSentence ? nextCommand : null
                                });
                                tempText = "";
                            }
                        }
                    }
                } else if (nextCommand) {
                    // Command with no preceding text
                    stages.push({ text: "", command: nextCommand });
                }
            }

            const finalStages = stages.filter(s => s.text.length > 0 || s.command);

            const startNarrative = async () => {
                console.log('Final Stages:', finalStages);

                // HYBRID STREAMING: Play first, buffer next (eliminates wait time)
                if (!premiumAudioPresent && isAudioEnabled) {
                    setIsSpeaking(true);

                    for (let i = 0; i < finalStages.length; i++) {
                        if (stopRef.current) break;

                        const stage = finalStages[i];
                        if (!stage.text || stage.text.length === 0) {
                            // Command-only stage
                            if (stage.command) {
                                executeNadiaCommand(stage.command);
                                await new Promise(r => setTimeout(r, 800));
                            }
                            continue;
                        }

                        const textForTTS = cleanTextForSpeech(stage.text);
                        if (textForTTS.length === 0) continue;

                        try {
                            // Execute command immediately (non-blocking)
                            if (stage.command) {
                                executeNadiaCommand(stage.command);
                            }

                            // Generate audio for THIS segment
                            const ttsResponse = await api.nadiaAudio(textForTTS, voiceMode);
                            if (ttsResponse.ok) {
                                const audioBlob = await ttsResponse.blob();
                                const audio = new Audio(URL.createObjectURL(audioBlob));

                                // Play immediately (no waiting!)
                                await new Promise((resolve) => {
                                    audio.onended = resolve;
                                    audio.onerror = () => {
                                        console.warn('Audio error');
                                        resolve();
                                    };
                                    audio.play().catch(e => {
                                        console.warn('Audio playback failed:', e);
                                        resolve();
                                    });

                                    // Stop check
                                    const checkStop = setInterval(() => {
                                        if (stopRef.current) {
                                            audio.pause();
                                            clearInterval(checkStop);
                                            resolve();
                                        }
                                    }, 100);
                                });
                            } else {
                                // Fallback to browser TTS
                                await new Promise((resolve) => {
                                    speak(textForTTS, resolve);
                                });
                            }
                        } catch (err) {
                            console.error('TTS Error:', err);
                            // Fallback to browser TTS
                            await new Promise((resolve) => {
                                speak(textForTTS, resolve);
                            });
                        }

                        // Tiny gap between segments
                        if (i < finalStages.length - 1) {
                            await new Promise(r => setTimeout(r, 100));
                        }
                    }

                    setIsSpeaking(false);
                } else if (premiumAudioPresent && isAudioEnabled) {
                    // Premium mode: use single audio file
                    for (let i = 0; i < finalStages.length; i++) {
                        if (stopRef.current) {
                            if (premiumAudioRef.current) {
                                premiumAudioRef.current.pause();
                                premiumAudioRef.current = null;
                            }
                            break;
                        }
                        const stage = finalStages[i];
                        if (stage.command) {
                            executeNadiaCommand(stage.command);
                        }
                        await new Promise(r => setTimeout(r, 800));
                    }
                } else {
                    // No audio: just execute commands
                    for (const stage of finalStages) {
                        if (stopRef.current) break;
                        if (stage.command) {
                            executeNadiaCommand(stage.command);
                            await new Promise(r => setTimeout(r, 1000));
                        }
                    }
                }
            };

            startNarrative().finally(() => {
                setIsNadiaStopping(false);
                stopRef.current = false;
            });

        } catch (err) {
            console.error("Nadia Command Error:", err);
            setChatMessages(prev => [...prev, { role: 'assistant', content: `Desculpe, tive um problema: ${err.message || 'Erro desconhecido'}. Pode tentar novamente?` }]);
        } finally {
            setIsThinking(false);
        }
    };

    if (!graphData && !loading) {
        return (
            <div className="max-w-4xl mx-auto px-6 py-20 text-center">
                <div className="bg-white p-12 rounded-[40px] shadow-premium border border-slate-100">
                    <div className="w-20 h-20 bg-brand-primary/10 text-brand-primary rounded-3xl flex items-center justify-center text-3xl mx-auto mb-6">🏜️</div>
                    <h2 className="text-2xl font-display font-bold text-brand-surface mb-2">Sem Grafo Ativo</h2>
                    <p className="text-brand-muted mb-8">Não encontramos um processamento ativo. Você pode iniciar um novo upload ou carregar um arquivo JSON de grafo exportado.</p>

                    <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                        <a href="/upload" className="px-8 py-4 bg-slate-100 text-slate-700 rounded-2xl font-bold hover:bg-slate-200 transition-all">
                            Ir para Upload
                        </a>
                        <label className="px-8 py-4 bg-brand-primary text-white rounded-2xl font-bold hover:bg-brand-secondary transition-all cursor-pointer shadow-lg shadow-brand-primary/20">
                            Carregar JSON do Grafo
                            <input type="file" accept=".json" onChange={handleFileUpload} className="hidden" />
                        </label>
                    </div>
                </div>
            </div>
        );
    }

    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center h-screen bg-seade-gray-light">
                <LoadingSpinner size="lg" />
                <p className="mt-4 text-brand-muted font-medium animate-pulse">Carregando mapa mental...</p>
            </div>
        );
    }

    return (
        <div className="flex h-[calc(100vh-80px)] overflow-hidden bg-white">
            {/* Sidebar Modernizada */}
            <aside className="w-85 border-r border-gray-100 bg-white/80 backdrop-blur-xl z-10 flex flex-col shadow-2xl">
                <div className="p-6 overflow-y-auto flex-1 custom-scrollbar">
                    <div className="flex items-center justify-between mb-8">
                        <h2 className="text-2xl font-display font-bold text-brand-surface tracking-tight">Explorador</h2>
                        <div className="p-2 bg-indigo-50 rounded-lg text-brand-primary">
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        </div>
                    </div>

                    <ErrorAlert message={error} onDismiss={() => setError(null)} />

                    {/* Estatísticas e Indicadores */}
                    {graphData?.stats && (
                        <div className="space-y-6 mb-8">
                            <div className="grid grid-cols-2 gap-3">
                                <div className="p-4 bg-slate-50 rounded-2xl border border-slate-100 shadow-sm transition-all hover:shadow-md">
                                    <span className="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">Densidade</span>
                                    <span className="text-xl font-display font-bold text-brand-surface">{(graphData.stats?.density ?? 0).toFixed(3)}</span>
                                </div>
                                <div className="p-4 bg-slate-50 rounded-2xl border border-slate-100 shadow-sm transition-all hover:shadow-md">
                                    <span className="block text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">Grau Médio</span>
                                    <span className="text-xl font-display font-bold text-brand-surface">{(graphData.stats?.avg_degree ?? 0).toFixed(2)}</span>
                                </div>
                            </div>

                            <div className="space-y-3">
                                <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2">Saúde do Grafo</h3>
                                <div className="p-4 bg-indigo-50/50 rounded-2xl border border-indigo-100/50">
                                    <div className="flex justify-between items-center mb-2">
                                        <span className="text-xs font-medium text-indigo-700">Consistência de Tipagem</span>
                                        <span className="text-xs font-bold text-indigo-700">{((graphData.stats?.type_consistency ?? 0) * 100).toFixed(0)}%</span>
                                    </div>
                                    <div className="w-full h-1.5 bg-indigo-100 rounded-full overflow-hidden">
                                        <div className="h-full bg-brand-primary" style={{ width: `${(graphData.stats?.type_consistency ?? 0) * 100}%` }}></div>
                                    </div>
                                </div>
                                <div className="p-4 bg-emerald-50/50 rounded-2xl border border-emerald-100/50">
                                    <div className="flex justify-between items-center mb-2">
                                        <span className="text-xs font-medium text-emerald-700">Completude (Sparsity)</span>
                                        <span className="text-xs font-bold text-emerald-700">{(graphData.stats?.avg_property_sparsity ?? 0).toFixed(0)}%</span>
                                    </div>
                                    <div className="w-full h-1.5 bg-emerald-100 rounded-full overflow-hidden">
                                        <div className="h-full bg-emerald-500" style={{ width: `${graphData.stats?.avg_property_sparsity ?? 0}%` }}></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Controles Internos */}
                    <div className="space-y-8">
                        <section>
                            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Interatividade</h3>
                            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-100">
                                <span className="text-xs font-bold text-slate-600">Mover Vizinhos Junto</span>
                                <button
                                    onClick={() => setMoveNeighbors(!moveNeighbors)}
                                    className={`w-10 h-5 rounded-full transition-all relative ${moveNeighbors ? 'bg-brand-primary' : 'bg-slate-300'}`}
                                >
                                    <div className={`absolute top-1 w-3 h-3 bg-white rounded-full transition-all ${moveNeighbors ? 'left-6' : 'left-1'}`} />
                                </button>
                            </div>
                        </section>

                        <section>
                            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Layout do Grafo</h3>
                            <div className="grid grid-cols-2 gap-2">
                                {['cose', 'readingGuide', 'circle', 'grid', 'breadthfirst'].map((l) => (
                                    <button
                                        key={l}
                                        onClick={() => changeLayout(l)}
                                        className="px-4 py-2 bg-white border border-slate-200 text-slate-600 rounded-xl text-xs font-bold hover:border-brand-primary hover:text-brand-primary transition-all capitalize"
                                    >
                                        {l === 'cose' ? 'Orgânico' : l === 'readingGuide' ? 'Fluxo/Guia' : l === 'breadthfirst' ? 'Árvore' : l}
                                    </button>
                                ))}
                            </div>
                        </section>

                        <section>
                            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Legenda de Entidades</h3>
                            <div className="space-y-3">
                                {graphData?.stats?.entity_types && Object.entries(graphData.stats.entity_types).map(([type, count]) => (
                                    <div key={type} className="flex items-center justify-between group p-2 hover:bg-slate-50 rounded-lg transition-colors cursor-default">
                                        <div className="flex items-center">
                                            <div
                                                className="w-3 h-3 rounded-full mr-3 shadow-sm"
                                                style={{ backgroundColor: getNodeColor(type) }}
                                            />
                                            <span className="text-sm font-medium text-slate-600 group-hover:text-brand-surface">{type}</span>
                                        </div>
                                        <span className="text-xs font-bold text-slate-400 bg-white border border-slate-100 px-2 py-0.5 rounded-full">{count}</span>
                                    </div>
                                ))}
                            </div>
                        </section>
                        <section>
                            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Dados Locais</h3>
                            <label className="flex items-center justify-center space-x-2 w-full py-3 bg-slate-100 text-slate-600 rounded-xl text-xs font-bold hover:bg-slate-200 transition-all cursor-pointer">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" /></svg>
                                <span>Carregar JSON</span>
                                <input type="file" accept=".json" onChange={handleFileUpload} className="hidden" />
                            </label>
                        </section>
                    </div>
                </div>

                {/* Detalhes do Item Selecionado - Floating UI feel */}
                {(selectedNode || selectedEdge) && (
                    <div className="p-6 bg-brand-surface text-white rounded-t-3xl shadow-2xl animate-in slide-in-from-bottom duration-300">
                        <div className="flex justify-between items-start mb-4">
                            <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-300">
                                {selectedNode ? 'Entidade Selecionada' : 'Relacionamento'}
                            </span>
                            <button onClick={() => { setSelectedNode(null); setSelectedEdge(null); cyRef.current.$('.highlighted').removeClass('highlighted dimmed'); }} className="text-indigo-300 hover:text-white">✕</button>
                        </div>
                        <h4 className="text-xl font-display font-bold mb-2">
                            {selectedNode ? selectedNode.label : `${selectedEdge.source} → ${selectedEdge.target}`}
                        </h4>
                        {selectedNode && (
                            <div className="space-y-2">
                                <p className="text-sm text-indigo-100/70">Tipo: <span className="text-white font-medium">{selectedNode.type}</span></p>
                                <p className="text-sm text-indigo-100/70">Conexões: <span className="text-white font-medium">{selectedNode.degree}</span></p>
                                <div className="pt-2 mt-2 border-t border-white/10">
                                    <span className="text-[10px] font-bold text-indigo-300 uppercase block mb-1">Importância Estrutural</span>
                                    <div className="flex items-center space-x-2">
                                        <div className="flex-1 h-1.5 bg-white/10 rounded-full overflow-hidden">
                                            <div
                                                className="h-full bg-brand-primary brightness-150"
                                                style={{ width: `${(graphData?.stats?.node_importance?.[selectedNode.id] || 0) * 100}%` }}
                                            />
                                        </div>
                                        <span className="text-xs font-bold font-mono">{(graphData?.stats?.node_importance?.[selectedNode.id] || 0).toFixed(2)}</span>
                                    </div>
                                </div>
                            </div>
                        )}
                        {selectedEdge && (
                            <p className="text-sm text-indigo-100/70">Relação: <span className="text-white font-medium">{selectedEdge.relation}</span></p>
                        )}
                    </div>
                )}

                {/* Toolbar Inferior */}
                <div className="p-4 border-t border-gray-100 grid grid-cols-2 gap-2">
                    <button onClick={fitGraph} className="flex items-center justify-center space-x-2 py-2.5 bg-slate-50 text-slate-600 rounded-xl text-xs font-bold hover:bg-slate-100 transition-all">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" /></svg>
                        <span>Centralizar</span>
                    </button>
                    <button onClick={exportPNG} className="flex items-center justify-center space-x-2 py-2.5 bg-brand-primary text-white rounded-xl text-xs font-bold hover:bg-brand-secondary transition-all shadow-lg shadow-indigo-100">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                        <span>Exportar</span>
                    </button>
                </div>

                {/* Painel Financeiro (Budget Tracking) */}
                <div className="mt-8 p-5 bg-white rounded-2xl border border-slate-100 shadow-sm">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Painel Financeiro</h3>
                        <span className="flex h-2 w-2 relative">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                        </span>
                    </div>

                    <div className="space-y-4">
                        <div className="p-3 bg-rose-50/50 rounded-xl border border-rose-100/50">
                            <div className="flex justify-between items-center mb-1">
                                <span className="text-[10px] font-bold text-rose-600 uppercase">Investimento</span>
                                <span className="text-xs font-mono font-bold text-rose-700">USD {usageStats.total_usd.toFixed(4)}</span>
                            </div>
                            <div className="w-full bg-rose-100 h-1 rounded-full overflow-hidden">
                                <div className="bg-rose-500 h-full w-full"></div>
                            </div>
                        </div>

                        <div className="p-3 bg-emerald-50/50 rounded-xl border border-emerald-100/50">
                            <div className="flex justify-between items-center mb-1">
                                <span className="text-[10px] font-bold text-emerald-600 uppercase">Economia Local</span>
                                <span className="text-xs font-mono font-bold text-emerald-700">USD {usageStats.estimated_savings_usd.toFixed(4)}</span>
                            </div>
                            <div className="w-full bg-emerald-100 h-1 rounded-full overflow-hidden">
                                <div className="bg-emerald-500 h-full w-full"></div>
                            </div>
                        </div>

                        <div className="flex justify-between items-center text-[10px] text-slate-400 px-1">
                            <span>{usageStats.messages_count} interações</span>
                            <span>{voiceMode === 'local' ? 'Modo Econômico Ativo' : 'Modo Premium'}</span>
                        </div>
                    </div>
                </div>
            </aside>

            {/* Canvas Principal */}
            <main className="flex-1 relative bg-[#f8fafc] group">
                <div className="absolute top-6 right-6 z-10 flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                    <div className="px-4 py-2 bg-white/80 backdrop-blur shadow-sm border border-slate-200 rounded-full text-[10px] font-bold text-slate-500 uppercase tracking-widest leading-none flex items-center">
                        <span className="w-2 h-2 bg-emerald-500 rounded-full mr-2 animate-pulse"></span>
                        Exploração Ativa
                    </div>
                </div>
                <div ref={containerRef} className="w-full h-full" />

                {/* Empty Graph Overlay */}
                {graphData && graphData.graph?.elements?.nodes?.length === 0 && (
                    <div className="absolute inset-0 flex items-center justify-center bg-white/50 backdrop-blur-[2px] z-[5]">
                        <div className="text-center p-8 bg-white rounded-3xl shadow-premium border border-slate-100 max-w-sm animate-in zoom-in-95 duration-500">
                            <div className="text-4xl mb-4">🔍</div>
                            <h3 className="text-lg font-bold text-brand-surface mb-2">Nenhuma Entidade Encontrada</h3>
                            <p className="text-sm text-brand-muted mb-6">O processamento terminou, mas não conseguimos extrair triplas semânticas deste documento com o esquema atual.</p>
                            <button
                                onClick={() => window.location.href = '/upload'}
                                className="px-6 py-2.5 bg-brand-primary text-white rounded-xl text-xs font-bold hover:bg-brand-secondary transition-all"
                            >
                                Tentar Novo Upload
                            </button>
                        </div>
                    </div>
                )}

                {/* Nadia Chatbot Interface */}
                <div
                    className={`absolute bottom-6 right-6 z-50 transition-all duration-300 ease-out ${nadiaOpen ? '' : 'w-16 h-16'}`}
                    style={nadiaOpen ? { width: chatSize.width, height: chatSize.height } : {}}
                >
                    {nadiaOpen ? (
                        <div className="w-full h-full bg-white rounded-3xl shadow-2xl border border-slate-100 flex flex-col overflow-hidden animate-in zoom-in-95 duration-300 relative">
                            {/* Resize Handle */}
                            <div
                                className="absolute top-0 left-0 w-6 h-6 cursor-nw-resize z-50 flex items-center justify-center group"
                                onMouseDown={startResizing}
                            >
                                <div className="w-1.5 h-1.5 bg-slate-200 rounded-full group-hover:bg-brand-primary transition-colors translate-x-1 translate-y-1"></div>
                            </div>

                            <div className="p-4 bg-brand-surface text-white flex justify-between items-center shrink-0">
                                <div className="flex items-center space-x-3 ml-4">
                                    <div className="w-8 h-8 bg-indigo-500 rounded-full flex items-center justify-center font-bold text-sm shadow-inner relative">
                                        N
                                        {isSpeaking && (
                                            <span className="absolute -bottom-1 -right-1 flex h-3 w-3">
                                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                                                <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                                            </span>
                                        )}
                                    </div>
                                    <div>
                                        <h4 className="font-bold text-sm tracking-tight flex items-center">
                                            Agent Nadia
                                            {isSpeaking && <span className="ml-2 text-[8px] bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded-full animate-pulse uppercase tracking-tighter">Falando</span>}
                                        </h4>
                                        <div className="flex items-center space-x-2">
                                            <span className="text-[10px] text-indigo-300 block">Expert em Mapeamento</span>
                                            {sessionCost > 0 && (
                                                <span className="text-[9px] bg-emerald-500/30 text-emerald-200 px-1.5 py-0.5 rounded-md font-mono border border-emerald-500/20">
                                                    USD {sessionCost.toFixed(4)}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                                <div className="flex items-center space-x-1">
                                    <button
                                        onClick={() => {
                                            const next = voiceMode === 'premium' ? 'local' : 'premium';
                                            setVoiceMode(next);
                                            localStorage.setItem('nadiaVoiceMode', next);
                                        }}
                                        className={`px-3 py-1.5 rounded-xl text-[10px] font-bold transition-all border ${voiceMode === 'premium'
                                            ? 'bg-indigo-500/20 border-indigo-400 text-indigo-100 hover:bg-indigo-500/30'
                                            : 'bg-emerald-500/20 border-emerald-400 text-emerald-100 hover:bg-emerald-500/30'
                                            }`}
                                        title={voiceMode === 'premium' ? "Mudar para Voz Local (Grátis)" : "Mudar para Voz Premium (OpenAI)"}
                                    >
                                        {voiceMode === 'premium' ? 'PREMIUM' : 'GRÁTIS'}
                                    </button>
                                    <button
                                        onClick={() => {
                                            if (isAudioEnabled) window.speechSynthesis.cancel();
                                            setIsAudioEnabled(!isAudioEnabled);
                                            localStorage.setItem('nadiaAudioEnabled', !isAudioEnabled);
                                        }}
                                        className={`p-2 rounded-xl transition-colors ${isAudioEnabled ? 'bg-white/20 text-white' : 'hover:bg-white/10 text-indigo-300'}`}
                                        title={isAudioEnabled ? "Desativar voz" : "Ativar voz"}
                                    >
                                        {isAudioEnabled ? (
                                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" /></svg>
                                        ) : (
                                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" /></svg>
                                        )}
                                    </button>
                                    <button onClick={() => {
                                        handleStopNadia();
                                        setNadiaOpen(false);
                                    }} className="hover:bg-white/10 p-2 rounded-xl transition-colors text-white">✕</button>
                                </div>
                            </div>

                            {/* Banner de Interrupção */}
                            {isNadiaStopping && (
                                <div className="bg-rose-500 text-white px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-center animate-in slide-in-from-top duration-300">
                                    Interrompendo resposta...
                                </div>
                            )}

                            <div className="flex-1 overflow-y-auto p-5 space-y-6 custom-scrollbar bg-slate-50/50">
                                {chatMessages.map((msg, i) => (
                                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-in slide-in-from-bottom-2 duration-300`}>
                                        <div className={`max-w-[85%] p-4 rounded-2xl text-sm leading-relaxed ${msg.role === 'user'
                                            ? 'bg-brand-primary text-white rounded-tr-none shadow-lg shadow-brand-primary/20'
                                            : 'bg-white text-slate-700 shadow-sm border border-slate-100 rounded-tl-none'
                                            }`}>
                                            {msg.role === 'assistant' && ReactMarkdown ? (
                                                <div className="markdown-content prose prose-sm prose-slate max-w-none">
                                                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                                                    {isSpeaking && i === chatMessages.length - 1 && (
                                                        <div className="mt-3 flex space-x-1 items-end h-3">
                                                            <div className="w-1 bg-brand-primary/40 rounded-full animate-voice-bar-1"></div>
                                                            <div className="w-1 bg-brand-primary/60 rounded-full animate-voice-bar-2"></div>
                                                            <div className="w-1 bg-brand-primary rounded-full animate-voice-bar-3"></div>
                                                        </div>
                                                    )}
                                                </div>
                                            ) : (
                                                <p className="whitespace-pre-wrap">{msg.content}</p>
                                            )}
                                        </div>
                                    </div>
                                ))}
                                {isThinking && (
                                    <div className="flex justify-start">
                                        <div className="bg-white p-4 rounded-2xl rounded-tl-none shadow-sm border border-slate-100 flex space-x-1.5 items-center">
                                            <div className="w-2 h-2 bg-brand-primary/40 rounded-full animate-bounce"></div>
                                            <div className="w-2 h-2 bg-brand-primary/60 rounded-full animate-bounce [animation-delay:0.2s]"></div>
                                            <div className="w-2 h-2 bg-brand-primary rounded-full animate-bounce [animation-delay:0.4s]"></div>
                                        </div>
                                    </div>
                                )}
                            </div>

                            <div className="p-4 bg-white border-t border-slate-100 flex space-x-2 shrink-0">
                                <input
                                    type="text"
                                    value={inputMessage}
                                    onChange={(e) => setInputMessage(e.target.value)}
                                    placeholder="Pergunte sobre o grafo..."
                                    className="flex-1 bg-slate-50 border border-slate-200 rounded-2xl px-5 py-3 text-sm focus:outline-none focus:ring-4 focus:ring-brand-primary/10 transition-all font-medium"
                                    onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                                />
                                <button
                                    onClick={handleSendMessage}
                                    disabled={isThinking || !inputMessage.trim() || isNadiaStopping}
                                    className="bg-brand-primary text-white p-3 rounded-2xl hover:bg-brand-secondary transition-all disabled:opacity-50 shadow-lg shadow-brand-primary/20 active:scale-95"
                                >
                                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" /></svg>
                                </button>
                                {(isThinking || isSpeaking) && (
                                    <button
                                        onClick={handleStopNadia}
                                        className="bg-rose-500 text-white p-3 rounded-2xl hover:bg-rose-600 transition-all shadow-lg shadow-rose-200 active:scale-95 animate-pulse"
                                        title="Parar Resposta"
                                    >
                                        <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
                                    </button>
                                )}
                            </div>
                        </div>
                    ) : (
                        <button
                            onClick={() => setNadiaOpen(true)}
                            className="w-16 h-16 bg-brand-surface text-white rounded-full shadow-2xl flex items-center justify-center hover:scale-110 active:scale-95 transition-all group relative overflow-hidden"
                        >
                            <div className="absolute inset-0 bg-gradient-to-tr from-brand-primary/20 to-transparent"></div>
                            <div className="absolute -top-1 -right-1 w-4 h-4 bg-emerald-500 rounded-full border-2 border-white animate-pulse z-10"></div>
                            <span className="text-2xl group-hover:rotate-12 transition-transform z-10">🤖</span>
                        </button>
                    )}
                </div>
            </main >
        </div >
    );
};

export default VisualizePage;
