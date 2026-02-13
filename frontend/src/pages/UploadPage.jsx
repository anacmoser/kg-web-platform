import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { ProgressBar, ErrorAlert, LoadingSpinner, JobStatusBadge } from '../components/SharedComponents';

const UploadPage = () => {
    const [files, setFiles] = useState([]);
    const [uploadedFiles, setUploadedFiles] = useState([]);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState(null);
    const [jobId, setJobId] = useState(null);
    const [jobStatus, setJobStatus] = useState(null);
    const [selectedFilenames, setSelectedFilenames] = useState([]);
    const [isDragging, setIsDragging] = useState(false);
    const [analyzeImages, setAnalyzeImages] = useState(false);
    const [userInstructions, setUserInstructions] = useState('');

    useEffect(() => {
        loadDocuments();
    }, []);

    useEffect(() => {
        if (jobId && jobStatus?.status !== 'completed' && jobStatus?.status !== 'failed') {
            const interval = setInterval(async () => {
                try {
                    const status = await api.getJobStatus(jobId);
                    setJobStatus(status);
                    if (status.status === 'completed' || status.status === 'failed') {
                        clearInterval(interval);
                    }
                } catch (err) {
                    console.error('Falha ao obter status do trabalho:', err);
                }
            }, 2000);
            return () => clearInterval(interval);
        }
    }, [jobId, jobStatus]);

    const loadDocuments = async () => {
        try {
            const docs = await api.listDocuments();
            setUploadedFiles(docs);
        } catch (err) {
            console.error('Falha ao carregar documentos:', err);
        }
    };

    const handleDragOver = (e) => {
        e.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = () => {
        setIsDragging(false);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragging(false);
        const droppedFiles = Array.from(e.dataTransfer.files);
        handleFiles(droppedFiles);
    };

    const handleFileSelect = (e) => {
        const selectedFiles = Array.from(e.target.files);
        handleFiles(selectedFiles);
        e.target.value = '';
    };

    const handleFiles = (newFiles) => {
        const validFiles = newFiles.filter(f =>
            f.name.toLowerCase().endsWith('.csv') ||
            f.name.toLowerCase().endsWith('.pdf') ||
            f.name.toLowerCase().endsWith('.docx')
        );

        if (validFiles.length !== newFiles.length) {
            setError('Alguns arquivos foram ignorados. Apenas PDF, CSV e DOCX são suportados.');
        }

        setFiles(prev => {
            const existingNames = new Set(prev.map(f => f.name + f.size));
            const uniqueNew = validFiles.filter(f => !existingNames.has(f.name + f.size));
            return [...prev, ...uniqueNew];
        });
    };

    const removeFile = (idx) => {
        setFiles(prev => prev.filter((_, i) => i !== idx));
    };

    const uploadFiles = async () => {
        setUploading(true);
        setError(null);

        try {
            const newlyUploadedNames = [];
            for (const file of files) {
                const res = await api.uploadDocument(file);
                newlyUploadedNames.push(res.filename || file.name);
            }
            await loadDocuments();
            setSelectedFilenames(prev => [...new Set([...prev, ...newlyUploadedNames])]);
            setFiles([]);
        } catch (err) {
            setError(err.message || 'Erro ao carregar documentos.');
        } finally {
            setUploading(false);
        }
    };

    const startPipeline = async () => {
        if (selectedFilenames.length === 0) {
            setError('Por favor, selecione pelo menos um documento para processar.');
            return;
        }

        setError(null);
        try {
            // We need to pass analyze_images in the startPipeline call if we want it used there,
            // or confirm if it's passed during upload.
            // Based on previous edits, the orchestrator needs config in start_job.
            // So we send it here if the backend route supports it.
            const result = await api.startPipeline(selectedFilenames, {
                analyze_images: analyzeImages,
                user_instructions: userInstructions
            });
            setJobId(result.job_id);
            setJobStatus({ status: result.status, progress: 0 });
        } catch (err) {
            setError(err.message);
        }
    };

    const toggleFileSelection = (filename) => {
        setSelectedFilenames(prev =>
            prev.includes(filename)
                ? prev.filter(f => f !== filename)
                : [...prev, filename]
        );
    };

    const selectAll = () => setSelectedFilenames(uploadedFiles.map(f => f.name));
    const deselectAll = () => setSelectedFilenames([]);

    const handleClearRepository = async () => {
        if (window.confirm('Tem certeza que deseja limpar todo o repositório e o cache?')) {
            try {
                await api.clearRepository();
                setUploadedFiles([]);
                setSelectedFilenames([]);
                setJobId(null);
                setJobStatus(null);
            } catch (err) {
                setError('Falha ao limpar o repositório: ' + err.message);
            }
        }
    };

    const formatFileSize = (bytes) => {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    };

    return (
        <div className="max-w-5xl mx-auto px-6 py-12">
            <header className="mb-10">
                <h1 className="text-4xl font-display font-extrabold text-brand-surface tracking-tight mb-2">
                    Central de <span className="gradient-text">Conhecimento</span>
                </h1>
                <p className="text-brand-muted">Envie e processe seus documentos para mapear relacionamentos estratégicos.</p>
            </header>

            <ErrorAlert message={error} onDismiss={() => setError(null)} />

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-10">
                {/* Coluna Esquerda: Upload */}
                <div className="lg:col-span-12">
                    <div
                        className={`group relative border-2 border-dashed rounded-3xl p-16 text-center transition-all duration-300 ${isDragging ? 'border-brand-primary bg-indigo-50/50 scale-[1.01]' : 'border-slate-200 bg-white hover:border-brand-primary/50'
                            }`}
                        onDragOver={handleDragOver}
                        onDragLeave={handleDragLeave}
                        onDrop={handleDrop}
                    >
                        <div className="text-7xl mb-6 group-hover:scale-110 transition-transform duration-500">📄</div>
                        <p className="text-xl font-bold text-brand-surface mb-2 tracking-tight">Arraste e solte seus documentos</p>
                        <p className="text-brand-muted mb-8">Formatos suportados: PDF, CSV e DOCX</p>

                        <input
                            type="file"
                            multiple
                            accept=".pdf,.csv,.docx"
                            onChange={handleFileSelect}
                            className="hidden"
                            id="file-input"
                        />
                        <label
                            htmlFor="file-input"
                            className="inline-flex items-center space-x-2 bg-brand-surface text-white px-8 py-3.5 rounded-2xl font-bold cursor-pointer hover:bg-black transition-all shadow-xl active:scale-95"
                        >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4" /></svg>
                            <span>Selecionar Arquivos</span>
                        </label>
                    </div>
                </div>

                {/* Coluna Meio: Fila de Upload e Documentos */}
                <div className="lg:col-span-7 space-y-8">
                    {/* Fila de Upload */}
                    {files.length > 0 && (
                        <section className="animate-in fade-in slide-in-from-left duration-500">
                            <div className="bg-white rounded-3xl shadow-premium border border-slate-100 overflow-hidden">
                                <div className="px-6 py-4 bg-slate-50 border-b border-slate-100 flex justify-between items-center">
                                    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Aguardando Envio</h3>
                                    <span className="bg-brand-primary/10 text-brand-primary text-[10px] font-bold px-2 py-0.5 rounded-full">{files.length}</span>
                                </div>
                                <div className="p-2 space-y-1">
                                    {files.map((file, idx) => (
                                        <div key={idx} className="flex items-center justify-between hover:bg-slate-50 p-4 rounded-2xl transition-colors group">
                                            <div className="flex items-center space-x-4">
                                                <div className="w-10 h-10 bg-indigo-50 text-brand-primary rounded-xl flex items-center justify-center text-lg">📄</div>
                                                <div className="flex flex-col">
                                                    <span className="text-sm font-bold text-slate-700 truncate max-w-[200px]">{file.name}</span>
                                                    <span className="text-xs text-slate-400 font-mono tracking-tighter">{formatFileSize(file.size)}</span>
                                                </div>
                                            </div>
                                            <button
                                                onClick={() => removeFile(idx)}
                                                className="opacity-0 group-hover:opacity-100 text-slate-300 hover:text-rose-500 transition-all p-2"
                                            >
                                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                                            </button>
                                        </div>
                                    ))}
                                </div>
                                <div className="p-4 bg-slate-50/50">
                                    <button
                                        onClick={uploadFiles}
                                        disabled={uploading}
                                        className="w-full bg-brand-primary text-white py-3.5 rounded-2xl font-bold hover:bg-brand-secondary disabled:bg-slate-200 disabled:text-slate-400 transition-all shadow-lg active:scale-95"
                                    >
                                        {uploading ? (
                                            <div className="flex items-center justify-center space-x-2">
                                                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                                                <span>Enviando...</span>
                                            </div>
                                        ) : 'Fazer Upload Agora'}
                                    </button>
                                </div>
                            </div>
                        </section>
                    )}

                    {/* Documentos Carregados */}
                    <section className="bg-white rounded-3xl shadow-premium border border-slate-100 overflow-hidden">
                        <div className="px-6 py-4 bg-slate-50 border-b border-slate-100 flex justify-between items-center">
                            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Repositório</h3>
                            {uploadedFiles.length > 0 && (
                                <div className="flex space-x-4">
                                    <button onClick={selectAll} className="text-[10px] font-bold text-brand-primary hover:underline uppercase tracking-wider">Selecionar Todos</button>
                                    <button onClick={deselectAll} className="text-[10px] font-bold text-slate-400 hover:underline uppercase tracking-wider">Limpar Seleção</button>
                                    <button onClick={handleClearRepository} className="text-[10px] font-bold text-rose-400 hover:underline uppercase tracking-wider">Limpar Repositório</button>
                                </div>
                            )}
                        </div>

                        <div className="p-2 max-h-[440px] overflow-y-auto custom-scrollbar">
                            {uploadedFiles.length === 0 ? (
                                <div className="p-12 text-center">
                                    <div className="text-4xl mb-4 grayscale opacity-30">📭</div>
                                    <p className="text-sm font-medium text-slate-400 italic">Nenhum documento disponível ainda.</p>
                                </div>
                            ) : (
                                <div className="space-y-1">
                                    {uploadedFiles.map((file, idx) => (
                                        <div
                                            key={idx}
                                            className={`flex items-center justify-between p-4 rounded-2xl transition-all cursor-pointer group ${selectedFilenames.includes(file.name) ? 'bg-indigo-50/60 ring-1 ring-brand-primary/20' : 'hover:bg-slate-50'}`}
                                            onClick={() => toggleFileSelection(file.name)}
                                        >
                                            <div className="flex items-center space-x-4">
                                                <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold transition-all ${selectedFilenames.includes(file.name) ? 'bg-brand-primary text-white rotate-6 scale-110 shadow-lg' : 'bg-slate-100 text-slate-400'}`}>
                                                    {selectedFilenames.includes(file.name) ? '✓' : 'DOC'}
                                                </div>
                                                <div className="flex flex-col">
                                                    <span className={`text-sm font-bold transition-colors ${selectedFilenames.includes(file.name) ? 'text-brand-primary' : 'text-slate-700'}`}>{file.name}</span>
                                                    <span className="text-[10px] font-mono font-bold text-slate-400 uppercase tracking-tighter italic">{formatFileSize(file.size)}</span>
                                                </div>
                                            </div>
                                            <div className="w-5 h-5 rounded-full border-2 border-slate-200 flex items-center justify-center group-hover:border-brand-primary transition-all">
                                                {selectedFilenames.includes(file.name) && <div className="w-2.5 h-2.5 bg-brand-primary rounded-full animate-in zoom-in duration-300"></div>}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </section>
                </div>

                {/* Coluna Direita: Status e Ação */}
                <div className="lg:col-span-5 space-y-6">
                    <div className="sticky top-28 space-y-6">
                        {/* Botão de Extração */}
                        <div className="p-2 bg-white rounded-[32px] shadow-premium border border-slate-100">
                            <div className="flex items-center space-x-2 mb-4 px-4 pt-2">
                                <input
                                    type="checkbox"
                                    id="analyzeImages"
                                    checked={analyzeImages}
                                    onChange={(e) => setAnalyzeImages(e.target.checked)}
                                    className="w-4 h-4 text-brand-primary border-slate-300 rounded focus:ring-brand-primary cursor-pointer"
                                />
                                <label htmlFor="analyzeImages" className="text-sm font-bold text-slate-600 select-none cursor-pointer hover:text-brand-primary transition-colors">
                                    Processar Imagens e Gráficos (IA Vision)
                                </label>
                            </div>

                            <div className="px-4 pb-4">
                                <label className="block text-xs font-bold text-slate-400 uppercase tracking-widest mb-2 px-1">Instruções de Mapeamento (Opcional)</label>
                                <textarea
                                    value={userInstructions}
                                    onChange={(e) => setUserInstructions(e.target.value)}
                                    placeholder="Ex: 'Foque em entidades do tipo Local e Data' ou 'Ignore menções a leis específicas'..."
                                    className="w-full h-24 bg-slate-50 border border-slate-200 rounded-2xl p-4 text-sm focus:outline-none focus:ring-4 focus:ring-brand-primary/10 transition-all font-medium resize-none"
                                />
                            </div>

                            <button
                                onClick={startPipeline}
                                disabled={selectedFilenames.length === 0 || (jobStatus && jobStatus.status === 'processing')}
                                className="w-full relative group overflow-hidden bg-brand-surface text-white p-6 rounded-[28px] font-bold text-xl hover:bg-black disabled:bg-slate-100 disabled:text-slate-400 transition-all shadow-2xl active:scale-[0.98] disabled:shadow-none"
                            >
                                <div className="absolute inset-x-0 bottom-0 h-1 bg-gradient-to-r from-brand-primary to-brand-accent transform scale-x-0 group-hover:scale-x-100 transition-transform origin-left duration-500"></div>
                                <div className="flex flex-col items-center">
                                    <span className="mb-1 uppercase text-[10px] tracking-[0.2em] font-extrabold text-indigo-400/80 group-disabled:hidden">Inteligência Ativa</span>
                                    <span>
                                        {selectedFilenames.length > 0
                                            ? `Mapear ${selectedFilenames.length} Documentos`
                                            : 'Selecionar para Mapear'
                                        }
                                    </span>
                                </div>
                            </button>
                        </div>

                        {/* Status do Job */}
                        {jobStatus && (
                            <div className="bg-white rounded-3xl shadow-premium border border-slate-100 overflow-hidden animate-in slide-in-from-right duration-500">
                                <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
                                    <h3 className="font-display font-bold text-slate-800">Status da Operação</h3>
                                    <JobStatusBadge status={jobStatus.status} />
                                </div>

                                <div className="p-6 space-y-6">
                                    <ProgressBar progress={jobStatus.progress || 0} status={jobStatus.status} />

                                    {jobStatus.current_stage && (
                                        <div className="bg-indigo-50/40 rounded-2xl p-4 border border-indigo-100/50">
                                            <div className="flex items-center justify-between mb-2">
                                                <div className="flex items-center space-x-3">
                                                    <div className="w-2 h-2 bg-brand-primary rounded-full animate-ping"></div>
                                                    <span className="text-[10px] uppercase font-bold text-brand-muted tracking-widest">Etapa Atual</span>
                                                </div>
                                                {jobStatus.estimated_total_time && jobStatus.status === 'processing' && (
                                                    <span className="text-[10px] font-bold text-brand-primary/60">
                                                        Tempo Restante: {Math.max(0, Math.round(jobStatus.estimated_total_time * (1 - jobStatus.progress)))}s
                                                    </span>
                                                )}
                                            </div>
                                            <p className="text-lg font-display font-bold text-brand-primary capitalize">{jobStatus.current_stage}</p>
                                        </div>
                                    )}

                                    {jobStatus.usage && (
                                        <div className="grid grid-cols-1 gap-4">
                                            <div className="p-5 bg-emerald-50/40 rounded-2xl border border-emerald-100/50 flex flex-col items-center text-center">
                                                <span className="text-[10px] uppercase font-bold text-emerald-600/60 tracking-widest mb-1">Custo Estimado</span>
                                                <span className="text-3xl font-display font-black text-emerald-600">${jobStatus.usage.total_cost.toFixed(4)}</span>
                                                <span className="mt-2 text-[10px] font-bold text-emerald-600/40 uppercase tracking-tighter">
                                                    {(jobStatus.usage.input_tokens + jobStatus.usage.output_tokens).toLocaleString()} tokens processados
                                                </span>
                                            </div>
                                        </div>
                                    )}

                                    {jobStatus.status === 'completed' && (
                                        <a
                                            href={`/visualize?job=${jobId}`}
                                            className="block w-full text-center bg-emerald-500 text-white py-4 rounded-2xl font-bold text-lg hover:bg-emerald-600 transition-all shadow-xl shadow-emerald-100 animate-bounce-short"
                                        >
                                            Explorar Grafo →
                                        </a>
                                    )}

                                    {jobStatus.error && (
                                        <div className="p-4 bg-rose-50 rounded-2xl border border-rose-100">
                                            <p className="text-xs font-bold text-rose-400 uppercase tracking-widest mb-1">Erro no Processamento</p>
                                            <p className="text-sm text-rose-700 font-medium">{jobStatus.error}</p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default UploadPage;
