import React, { useState, useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import { api } from '../api/client';
import { LoadingSpinner, ErrorAlert, StatCard } from '../components/SharedComponents';

const VisualizePage = () => {
    const [graphData, setGraphData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selectedNode, setSelectedNode] = useState(null);
    const [filters, setFilters] = useState({});
    const cyRef = useRef(null);
    const containerRef = useRef(null);

    useEffect(() => {
        // Get job ID from URL query params
        const params = new URLSearchParams(window.location.search);
        const jobId = params.get('job');

        if (jobId) {
            loadGraph(jobId);
        } else {
            setError('No job ID provided');
            setLoading(false);
        }
    }, []);

    const loadGraph = async (jobId) => {
        try {
            setLoading(true);
            const data = await api.getGraph(jobId);
            setGraphData(data);
            setError(null);

            // Initialize Cytoscape after data is loaded
            setTimeout(() => initializeCytoscape(data.graph), 100);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const initializeCytoscape = (graphElements) => {
        if (!containerRef.current || !graphElements) return;

        const cy = cytoscape({
            container: containerRef.current,
            elements: graphElements.elements,
            style: [
                {
                    selector: 'node',
                    style: {
                        'background-color': (ele) => getNodeColor(ele.data('type')),
                        'label': 'data(label)',
                        'width': (ele) => Math.max(30, Math.min(80, ele.data('degree') * 8)),
                        'height': (ele) => Math.max(30, Math.min(80, ele.data('degree') * 8)),
                        'font-size': '12px',
                        'text-valign': 'center',
                        'text-halign': 'center',
                        'color': '#fff',
                        'text-outline-color': '#000',
                        'text-outline-width': 2
                    }
                },
                {
                    selector: 'edge',
                    style: {
                        'width': (ele) => Math.max(1, ele.data('weight') * 2),
                        'line-color': '#0066CC',
                        'target-arrow-color': '#0066CC',
                        'target-arrow-shape': 'triangle',
                        'curve-style': 'bezier',
                        'label': 'data(relation)',
                        'font-size': '10px',
                        'text-rotation': 'autorotate',
                        'text-margin-y': -10
                    }
                },
                {
                    selector: 'node.highlighted',
                    style: {
                        'border-width': 4,
                        'border-color': '#FFD700'
                    }
                },
                {
                    selector: 'node.dimmed',
                    style: {
                        'opacity': 0.3
                    }
                },
                {
                    selector: 'edge.dimmed',
                    style: {
                        'opacity': 0.2
                    }
                }
            ],
            layout: {
                name: 'cose',
                animate: true,
                animationDuration: 1000,
                nodeRepulsion: 8000,
                idealEdgeLength: 100,
                gravity: 0.1
            }
        });

        // Event handlers
        cy.on('tap', 'node', (evt) => {
            const node = evt.target;
            setSelectedNode(node.data());

            // Highlight connected nodes
            cy.elements().removeClass('highlighted dimmed');
            node.addClass('highlighted');
            node.neighborhood().addClass('highlighted');
            cy.elements().not(node.neighborhood().union(node)).addClass('dimmed');
        });

        cy.on('tap', (evt) => {
            if (evt.target === cy) {
                // Clicked on background
                setSelectedNode(null);
                cy.elements().removeClass('highlighted dimmed');
            }
        });

        cyRef.current = cy;
    };

    const getNodeColor = (type) => {
        const colors = {
            'PERSON': '#0066CC',
            'ORGANIZATION': '#4A90E2',
            'CONCEPT': '#7AB8E8',
            'TERM': '#A8D5F2',
            'LOCATION': '#0052A3',
            'DATE': '#003D7A',
            'Unknown': '#999999'
        };
        return colors[type] || colors['Unknown'];
    };

    const changeLayout = (layoutName) => {
        if (!cyRef.current) return;

        const layouts = {
            cose: { name: 'cose', animate: true, nodeRepulsion: 8000 },
            circle: { name: 'circle', animate: true },
            grid: { name: 'grid', animate: true },
            breadthfirst: { name: 'breadthfirst', animate: true, directed: true }
        };

        cyRef.current.layout(layouts[layoutName] || layouts.cose).run();
    };

    const fitGraph = () => {
        if (cyRef.current) {
            cyRef.current.fit(null, 50);
        }
    };

    const exportPNG = () => {
        if (cyRef.current) {
            const png = cyRef.current.png({ full: true, scale: 2 });
            const link = document.createElement('a');
            link.href = png;
            link.download = 'knowledge-graph.png';
            link.click();
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-screen">
                <LoadingSpinner size="lg" />
            </div>
        );
    }

    return (
        <div className="flex h-screen">
            {/* Sidebar */}
            <div className="w-80 bg-white shadow-lg p-6 overflow-y-auto">
                <h2 className="text-2xl font-bold mb-6">Graph Controls</h2>

                <ErrorAlert message={error} onDismiss={() => setError(null)} />

                {/* Stats */}
                {graphData?.stats && (
                    <div className="mb-6 space-y-3">
                        <StatCard title="Nodes" value={graphData.stats.node_count} icon="🔵" />
                        <StatCard title="Edges" value={graphData.stats.edge_count} icon="🔗" />
                    </div>
                )}

                {/* Layout Controls */}
                <div className="mb-6">
                    <h3 className="font-semibold mb-3">Layout</h3>
                    <div className="grid grid-cols-2 gap-2">
                        <button onClick={() => changeLayout('cose')} className="px-3 py-2 bg-seade-blue-primary text-white rounded text-sm hover:bg-seade-blue-dark">
                            Force
                        </button>
                        <button onClick={() => changeLayout('circle')} className="px-3 py-2 bg-seade-blue-primary text-white rounded text-sm hover:bg-seade-blue-dark">
                            Circle
                        </button>
                        <button onClick={() => changeLayout('grid')} className="px-3 py-2 bg-seade-blue-primary text-white rounded text-sm hover:bg-seade-blue-dark">
                            Grid
                        </button>
                        <button onClick={() => changeLayout('breadthfirst')} className="px-3 py-2 bg-seade-blue-primary text-white rounded text-sm hover:bg-seade-blue-dark">
                            Tree
                        </button>
                    </div>
                </div>

                {/* View Controls */}
                <div className="mb-6">
                    <h3 className="font-semibold mb-3">View</h3>
                    <button onClick={fitGraph} className="w-full px-3 py-2 bg-gray-200 rounded hover:bg-gray-300 mb-2">
                        Fit to Screen
                    </button>
                    <button onClick={exportPNG} className="w-full px-3 py-2 bg-gray-200 rounded hover:bg-gray-300">
                        Export PNG
                    </button>
                </div>

                {/* Entity Type Legend */}
                {graphData?.stats?.entity_types && (
                    <div className="mb-6">
                        <h3 className="font-semibold mb-3">Entity Types</h3>
                        <div className="space-y-2">
                            {Object.entries(graphData.stats.entity_types).map(([type, count]) => (
                                <div key={type} className="flex items-center justify-between text-sm">
                                    <div className="flex items-center">
                                        <div
                                            className="w-4 h-4 rounded-full mr-2"
                                            style={{ backgroundColor: getNodeColor(type) }}
                                        />
                                        <span>{type}</span>
                                    </div>
                                    <span className="text-seade-gray-dark">{count}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Selected Node Details */}
                {selectedNode && (
                    <div className="bg-seade-gray-light p-4 rounded">
                        <h3 className="font-semibold mb-2">Selected Node</h3>
                        <p className="text-lg font-bold mb-1">{selectedNode.label}</p>
                        <p className="text-sm text-seade-gray-dark mb-1">Type: {selectedNode.type}</p>
                        <p className="text-sm text-seade-gray-dark">Connections: {selectedNode.degree}</p>
                    </div>
                )}
            </div>

            {/* Graph Canvas */}
            <div className="flex-1 bg-seade-gray-light relative">
                <div ref={containerRef} className="w-full h-full" />
            </div>
        </div>
    );
};

export default VisualizePage;
