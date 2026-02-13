import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { LoadingSpinner, ErrorAlert } from '../components/SharedComponents';
import JobRepository from '../components/JobRepository';

const OntologyPage = () => {
    const [ontology, setOntology] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [searchTerm, setSearchTerm] = useState('');

    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        let jobId = params.get('job');

        // If no job in URL, try localStorage (persisted from VisualizePage)
        if (!jobId) {
            jobId = localStorage.getItem('lastJobId');
        }

        if (jobId) {
            loadOntology(jobId);
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
                setOntology(data);
                setError(null);
            } catch (err) {
                setError('Arquivo JSON inválido: ' + err.message);
            }
        };
        reader.readAsText(file);
    };

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
            <div className="flex flex-col items-center justify-center h-screen bg-seade-gray-light">
                <LoadingSpinner size="lg" />
                <p className="mt-4 text-brand-muted font-medium animate-pulse">Mapeando ontologia...</p>
            </div>
        );
    }

    const filteredEntities = ontology?.entities ? filterItems(ontology.entities, 'name') : [];
    const filteredRelations = ontology?.relations ? filterItems(ontology.relations, 'label') : [];

    if (!ontology && !loading) {
        return (
            <div className="max-w-4xl mx-auto px-6 py-20 text-center">
                <div className="bg-white p-12 rounded-[40px] shadow-premium border border-slate-100">
                    <div className="w-20 h-20 bg-indigo-50 text-brand-primary rounded-3xl flex items-center justify-center text-3xl mx-auto mb-6">📂</div>
                    <h2 className="text-2xl font-display font-bold text-brand-surface mb-2">Sem Ontologia Ativa</h2>
                    <p className="text-brand-muted mb-8">Nenhum ID de processamento foi encontrado ou o ID expirou. Você pode carregar um arquivo JSON de ontologia manualmente.</p>

                    <label className="inline-flex items-center px-8 py-4 bg-brand-primary text-white rounded-2xl font-bold hover:bg-brand-secondary transition-all cursor-pointer shadow-lg shadow-brand-primary/20">
                        <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>
                        Carregar Ontologia JSON
                        <input type="file" accept=".json" onChange={handleFileUpload} className="hidden" />
                    </label>
                </div>
            </div>
        );
    }

    return (
        <div className="max-w-6xl mx-auto px-6 py-12">
            <JobRepository onLoad={loadOntology} activeJobId={null} />
            <header className="mb-10">
                <h1 className="text-4xl font-display font-extrabold text-brand-surface tracking-tight mb-2">
                    Visualizador de <span className="gradient-text">Ontologia</span>
                </h1>
                <p className="text-brand-muted">Explore o esquema semântico extraído: tipos de entidades e padrões de relacionamento.</p>
            </header>

            <ErrorAlert message={error} onDismiss={() => setError(null)} />

            {/* Guia de Vocabulário */}
            <section className="mb-12 bg-white rounded-3xl shadow-premium border border-slate-100 overflow-hidden">
                <div className="px-6 py-5 bg-slate-50 border-b border-slate-100">
                    <h2 className="text-sm font-bold text-slate-500 uppercase tracking-widest">Guia de Leitura & Vocabulário</h2>
                </div>
                <div className="p-8 grid grid-cols-1 md:grid-cols-3 gap-8">
                    <div className="space-y-3">
                        <div className="w-10 h-10 bg-indigo-50 text-brand-primary rounded-xl flex items-center justify-center text-lg">💡</div>
                        <h3 className="font-bold text-brand-surface">Entidades</h3>
                        <p className="text-sm text-brand-muted leading-relaxed">Representam os "substantivos" do seu documento: pessoas, empresas, locais ou conceitos abstratos que possuem identidade própria.</p>
                    </div>
                    <div className="space-y-3">
                        <div className="w-10 h-10 bg-emerald-50 text-emerald-600 rounded-xl flex items-center justify-center text-lg">🔗</div>
                        <h3 className="font-bold text-brand-surface">Relacionamentos</h3>
                        <p className="text-sm text-brand-muted leading-relaxed">São os "verbos" que conectam as entidades. Eles mapeiam como uma informação influencia ou pertence a outra no contexto do texto.</p>
                    </div>
                    <div className="space-y-3">
                        <div className="w-10 h-10 bg-amber-50 text-amber-600 rounded-xl flex items-center justify-center text-lg">🏆</div>
                        <h3 className="font-bold text-brand-surface">Importância</h3>
                        <p className="text-sm text-brand-muted leading-relaxed">Nós mais centrais (hubs) indicam temas recorrentes ou pontos de convergência crítica em todo o conjunto de dados processado.</p>
                    </div>
                </div>
            </section>

            {/* Barra de Pesquisa */}
            <div className="relative mb-10 group">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                    <svg className="w-5 h-5 text-slate-400 group-focus-within:text-brand-primary transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
                </div>
                <input
                    type="text"
                    placeholder="Filtrar entidades e relacionamentos..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="w-full pl-12 pr-4 py-4 bg-white border border-slate-200 rounded-2xl shadow-premium focus:outline-none focus:ring-2 focus:ring-brand-primary/20 focus:border-brand-primary transition-all text-slate-700 font-medium"
                />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Tipos de Entidades */}
                <section className="bg-white rounded-3xl shadow-premium border border-slate-100 overflow-hidden">
                    <div className="px-6 py-5 bg-slate-50 border-b border-slate-100 flex items-center justify-between">
                        <h2 className="text-sm font-bold text-slate-500 uppercase tracking-widest">Tipos de Entidades</h2>
                        <span className="bg-brand-primary text-white text-[10px] font-bold px-2 py-0.5 rounded-full">{filteredEntities.length}</span>
                    </div>
                    <div className="p-4 space-y-3 max-h-[500px] overflow-y-auto custom-scrollbar">
                        {filteredEntities.length === 0 ? (
                            <p className="p-8 text-center text-slate-400 italic text-sm">Nenhuma entidade encontrada</p>
                        ) : (
                            filteredEntities.map((entity, idx) => (
                                <div key={idx} className="p-4 bg-slate-50/50 rounded-2xl border border-transparent hover:border-brand-primary/20 hover:bg-white transition-all group">
                                    <div className="flex items-center justify-between mb-2">
                                        <h3 className="font-display font-bold text-brand-surface group-hover:text-brand-primary transition-colors">{entity.name}</h3>
                                        <div className="flex items-center space-x-2">
                                            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Instâncias</span>
                                            <span className="bg-white border border-slate-200 text-brand-surface text-xs font-bold px-2 py-0.5 rounded-lg shadow-sm">
                                                {entity.count || 0}
                                            </span>
                                        </div>
                                    </div>
                                    {entity.description && (
                                        <p className="text-sm text-brand-muted leading-relaxed">{entity.description}</p>
                                    )}
                                </div>
                            ))
                        )}
                    </div>
                </section>

                {/* Tipos de Relacionamentos */}
                <section className="bg-white rounded-3xl shadow-premium border border-slate-100 overflow-hidden">
                    <div className="px-6 py-5 bg-slate-50 border-b border-slate-100 flex items-center justify-between">
                        <h2 className="text-sm font-bold text-slate-500 uppercase tracking-widest">Tipos de Relação</h2>
                        <span className="bg-emerald-500 text-white text-[10px] font-bold px-2 py-0.5 rounded-full">{filteredRelations.length}</span>
                    </div>
                    <div className="p-4 space-y-3 max-h-[500px] overflow-y-auto custom-scrollbar">
                        {filteredRelations.length === 0 ? (
                            <p className="p-8 text-center text-slate-400 italic text-sm">Nenhum relacionamento encontrado</p>
                        ) : (
                            filteredRelations.map((relation, idx) => (
                                <div key={idx} className="p-4 bg-slate-50/50 rounded-2xl border border-transparent hover:border-emerald-500/20 hover:bg-white transition-all group">
                                    <div className="flex items-center justify-between mb-2">
                                        <h3 className="font-display font-bold text-brand-surface group-hover:text-emerald-600 transition-colors uppercase tracking-tight text-sm">{relation.label}</h3>
                                        <div className="flex items-center space-x-2">
                                            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Conexões</span>
                                            <span className="bg-white border border-slate-200 text-emerald-600 text-xs font-bold px-2 py-0.5 rounded-lg shadow-sm">
                                                {relation.count || 0}
                                            </span>
                                        </div>
                                    </div>
                                    {relation.description && (
                                        <p className="text-sm text-brand-muted leading-relaxed mb-3">{relation.description}</p>
                                    )}
                                    <div className="flex flex-wrap gap-2">
                                        {(relation.source || relation.target) && (
                                            <div className="flex items-center space-x-2 bg-white/60 p-2 rounded-xl border border-slate-100">
                                                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest px-1.5 py-0.5 bg-slate-50 rounded italic">{relation.source || '?'}</span>
                                                <svg className="w-3 h-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M14 5l7 7m0 0l-7 7m7-7H3" /></svg>
                                                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest px-1.5 py-0.5 bg-slate-50 rounded italic">{relation.target || '?'}</span>
                                            </div>
                                        )}
                                        {relation.importance === 'high' && (
                                            <span className="text-[9px] font-bold bg-amber-100 text-amber-700 px-2 py-1 rounded-lg uppercase tracking-wider">Altamente Estratégico</span>
                                        )}
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </section>
            </div>

            {/* Resumo da Ontologia */}
            {ontology && (
                <div className="mt-12 bg-brand-surface text-white p-10 rounded-[40px] shadow-2xl relative overflow-hidden group">
                    <div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none group-hover:scale-110 transition-transform duration-1000">
                        <svg className="w-64 h-64" fill="currentColor" viewBox="0 0 24 24"><path d="M9 21c0 .55.45 1 1 1h4c.55 0 1-.45 1-1v-1H9v1zm3-19C8.14 2 5 5.14 5 9c0 2.38 1.19 4.47 3 5.74V17c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-2.26c1.81-1.27 3-3.36 3-5.74 0-3.86-3.14-7-7-7zm2.85 11.1l-.85.6V16h-4v-2.3l-.85-.6C8.29 12.31 7 10.73 7 9c0-2.76 2.24-5 5-5s5 2.24 5 5c0 1.73-1.29 3.31-3.15 4.1z" /></svg>
                    </div>

                    <h3 className="text-xs font-bold text-indigo-300 uppercase tracking-[0.3em] mb-8">Panorama Semântico</h3>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-8 relative z-10">
                        <div className="space-y-1">
                            <p className="text-4xl font-display font-black text-white">
                                {ontology.entities?.length || 0}
                            </p>
                            <p className="text-[10px] font-bold text-indigo-200 uppercase tracking-widest">Tipos de Entidade</p>
                        </div>
                        <div className="space-y-1">
                            <p className="text-4xl font-display font-black text-indigo-400">
                                {ontology.relations?.length || 0}
                            </p>
                            <p className="text-[10px] font-bold text-indigo-200 uppercase tracking-widest">Tipos de Relação</p>
                        </div>
                        <div className="space-y-1">
                            <p className="text-4xl font-display font-black text-emerald-400">
                                {ontology.entities?.reduce((sum, e) => sum + (e.count || 0), 0) || 0}
                            </p>
                            <p className="text-[10px] font-bold text-indigo-200 uppercase tracking-widest">Total de Entidades</p>
                        </div>
                        <div className="space-y-1">
                            <p className="text-4xl font-display font-black text-amber-400">
                                {ontology.relations?.reduce((sum, r) => sum + (r.count || 0), 0) || 0}
                            </p>
                            <p className="text-[10px] font-bold text-indigo-200 uppercase tracking-widest">Total de Relações</p>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default OntologyPage;
