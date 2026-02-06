import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { LoadingSpinner, ErrorAlert } from '../components/SharedComponents';

const OntologyPage = () => {
    const [ontology, setOntology] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [searchTerm, setSearchTerm] = useState('');

    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        const jobId = params.get('job');

        if (jobId) {
            loadOntology(jobId);
        } else {
            setError('No job ID provided');
            setLoading(false);
        }
    }, []);

    const loadOntology = async (jobId) => {
        try {
            setLoading(true);
            const data = await api.getOntology(jobId);
            setOntology(data);
            setError(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const filterItems = (items, searchField) => {
        if (!searchTerm) return items;
        return items.filter(item =>
            item[searchField]?.toLowerCase().includes(searchTerm.toLowerCase())
        );
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-screen">
                <LoadingSpinner size="lg" />
            </div>
        );
    }

    const filteredEntities = ontology?.entities ? filterItems(ontology.entities, 'name') : [];
    const filteredRelations = ontology?.relations ? filterItems(ontology.relations, 'label') : [];

    return (
        <div className="p-8 max-w-6xl mx-auto">
            <h1 className="text-3xl mb-6">Ontology Viewer</h1>

            <ErrorAlert message={error} onDismiss={() => setError(null)} />

            {/* Search Bar */}
            <div className="mb-6">
                <input
                    type="text"
                    placeholder="Search entities and relations..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-full px-4 py-2 border border-seade-gray-medium rounded-lg focus:outline-none focus:ring-2 focus:ring-seade-blue-primary"
                />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Entity Types */}
                <div className="bg-white rounded-lg shadow p-6">
                    <h2 className="text-xl font-bold mb-4">Entity Types</h2>
                    {filteredEntities.length === 0 ? (
                        <p className="text-seade-gray-dark">No entities found</p>
                    ) : (
                        <div className="space-y-3">
                            {filteredEntities.map((entity, idx) => (
                                <div key={idx} className="border-l-4 border-seade-blue-primary pl-4 py-2">
                                    <div className="flex items-center justify-between mb-1">
                                        <h3 className="font-semibold text-lg">{entity.name}</h3>
                                        <span className="bg-seade-blue-light text-white px-3 py-1 rounded-full text-sm">
                                            {entity.count || 0}
                                        </span>
                                    </div>
                                    {entity.description && (
                                        <p className="text-sm text-seade-gray-dark">{entity.description}</p>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Relation Types */}
                <div className="bg-white rounded-lg shadow p-6">
                    <h2 className="text-xl font-bold mb-4">Relation Types</h2>
                    {filteredRelations.length === 0 ? (
                        <p className="text-seade-gray-dark">No relations found</p>
                    ) : (
                        <div className="space-y-3">
                            {filteredRelations.map((relation, idx) => (
                                <div key={idx} className="border-l-4 border-seade-blue-dark pl-4 py-2">
                                    <div className="flex items-center justify-between mb-1">
                                        <h3 className="font-semibold">{relation.label}</h3>
                                        <span className="bg-seade-blue-dark text-white px-3 py-1 rounded-full text-sm">
                                            {relation.count || 0}
                                        </span>
                                    </div>
                                    {relation.description && (
                                        <p className="text-sm text-seade-gray-dark mb-1">{relation.description}</p>
                                    )}
                                    {(relation.source || relation.target) && (
                                        <p className="text-xs text-seade-gray-dark">
                                            {relation.source} → {relation.target}
                                        </p>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* Summary Stats */}
            {ontology && (
                <div className="mt-6 bg-seade-gray-light p-6 rounded-lg">
                    <h3 className="font-semibold mb-3">Summary</h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="text-center">
                            <p className="text-3xl font-bold text-seade-blue-primary">
                                {ontology.entities?.length || 0}
                            </p>
                            <p className="text-sm text-seade-gray-dark">Entity Types</p>
                        </div>
                        <div className="text-center">
                            <p className="text-3xl font-bold text-seade-blue-primary">
                                {ontology.relations?.length || 0}
                            </p>
                            <p className="text-sm text-seade-gray-dark">Relation Types</p>
                        </div>
                        <div className="text-center">
                            <p className="text-3xl font-bold text-seade-blue-primary">
                                {ontology.entities?.reduce((sum, e) => sum + (e.count || 0), 0) || 0}
                            </p>
                            <p className="text-sm text-seade-gray-dark">Total Entities</p>
                        </div>
                        <div className="text-center">
                            <p className="text-3xl font-bold text-seade-blue-primary">
                                {ontology.relations?.reduce((sum, r) => sum + (r.count || 0), 0) || 0}
                            </p>
                            <p className="text-sm text-seade-gray-dark">Total Relations</p>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default OntologyPage;
