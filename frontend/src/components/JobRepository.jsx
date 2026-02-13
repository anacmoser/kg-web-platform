import React, { useState, useEffect } from 'react';
import { api } from '../api/client';

const JobRepository = ({ onLoad, activeJobId }) => {
    const [jobs, setJobs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [isOpen, setIsOpen] = useState(false);

    const fetchJobs = async () => {
        try {
            setLoading(true);
            const data = await api.listJobs();
            setJobs(data);
        } catch (error) {
            console.error("Failed to load jobs:", error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (isOpen) fetchJobs();
    }, [isOpen]);

    return (
        <>
            {/* Toggle Button */}
            <button
                onClick={() => setIsOpen(true)}
                className="fixed left-0 top-1/2 -translate-y-1/2 bg-white shadow-premium rounded-r-xl p-3 z-40 border border-slate-100 hover:w-12 w-8 transition-all group overflow-hidden"
                title="Histórico de Análises"
            >
                <div className="flex items-center">
                    <span className="text-xl">📂</span>
                </div>
            </button>

            {/* Drawer */}
            <div className={`fixed inset-y-0 left-0 w-80 bg-white shadow-2xl z-50 transform transition-transform duration-300 ease-in-out border-r border-slate-100 ${isOpen ? 'translate-x-0' : '-translate-x-full'}`}>
                <div className="p-6 h-full flex flex-col">
                    <div className="flex justify-between items-center mb-6">
                        <h3 className="font-display font-bold text-lg text-brand-surface">Histórico</h3>
                        <button onClick={() => setIsOpen(false)} className="text-slate-400 hover:text-brand-primary transition-colors">✕</button>
                    </div>

                    <div className="flex-1 overflow-y-auto custom-scrollbar space-y-3">
                        {loading ? (
                            <div className="text-center py-10 text-slate-400 animate-pulse">Carregando...</div>
                        ) : jobs.length === 0 ? (
                            <div className="text-center py-10 text-slate-400">Nenhuma análise encontrada.</div>
                        ) : (
                            jobs.map((job) => (
                                <div
                                    key={job.id}
                                    onClick={() => {
                                        onLoad(job.id);
                                        setIsOpen(false);
                                    }}
                                    className={`p-4 rounded-xl border cursor-pointer transition-all hover:shadow-md group ${activeJobId === job.id ? 'bg-indigo-50 border-indigo-200' : 'bg-white border-slate-100 hover:border-brand-primary/30'}`}
                                >
                                    <div className="flex justify-between items-start mb-2">
                                        <div className="font-bold text-sm text-brand-surface truncate max-w-[180px]" title={job.filenames?.[0]}>
                                            {job.filenames?.[0] || "Documento Sem Nome"}
                                        </div>
                                        {activeJobId === job.id && <span className="w-2 h-2 bg-brand-primary rounded-full"></span>}
                                    </div>
                                    <div className="flex justify-between items-center text-xs text-slate-400">
                                        <span>{new Date(job.date * 1000).toLocaleDateString('pt-BR')}</span>
                                        <span className="bg-slate-100 px-2 py-0.5 rounded-full text-[10px] font-bold">
                                            {job.node_count} nós
                                        </span>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>

                    <button
                        onClick={fetchJobs}
                        className="mt-4 w-full py-2 flex items-center justify-center space-x-2 text-xs font-bold text-slate-500 hover:bg-slate-50 rounded-lg transition-colors"
                    >
                        <span>↻ Atualizar Lista</span>
                    </button>
                </div>
            </div>

            {/* Backdrop */}
            {isOpen && (
                <div onClick={() => setIsOpen(false)} className="fixed inset-0 bg-black/20 backdrop-blur-[1px] z-40" />
            )}
        </>
    );
};

export default JobRepository;
