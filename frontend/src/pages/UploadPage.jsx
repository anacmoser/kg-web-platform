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
                    console.error('Failed to fetch job status:', err);
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
            console.error('Failed to load documents:', err);
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
        // Reset input so the same file can be selected again if removed
        e.target.value = '';
    };

    const handleFiles = (newFiles) => {
        const validFiles = newFiles.filter(f =>
            ['application/pdf', 'text/csv', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'].includes(f.type) ||
            f.name.toLowerCase().endsWith('.csv') ||
            f.name.toLowerCase().endsWith('.pdf') ||
            f.name.toLowerCase().endsWith('.docx')
        );

        if (validFiles.length !== newFiles.length) {
            setError('Some files were skipped. Only PDF, CSV, and DOCX files are supported.');
        }

        // Avoid adding the same file multiple times by comparing name and size
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
            setError(err.message);
        } finally {
            setUploading(false);
        }
    };

    const startPipeline = async () => {
        if (selectedFilenames.length === 0) {
            setError('Please select at least one document to process.');
            return;
        }

        setError(null);
        try {
            const result = await api.startPipeline(selectedFilenames);
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

    const selectAll = () => {
        setSelectedFilenames(uploadedFiles.map(f => f.name));
    };

    const deselectAll = () => {
        setSelectedFilenames([]);
    };

    const formatFileSize = (bytes) => {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    };

    return (
        <div className="p-8 max-w-4xl mx-auto">
            <h1 className="text-3xl mb-6">Upload Documents</h1>

            <ErrorAlert message={error} onDismiss={() => setError(null)} />

            {/* Upload Zone */}
            <div
                className={`border-2 border-dashed rounded-lg p-12 text-center mb-6 transition-colors ${isDragging ? 'border-seade-blue-primary bg-blue-50' : 'border-seade-gray-medium'
                    }`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
            >
                <div className="text-6xl mb-4">📁</div>
                <p className="text-lg mb-2">Drag & drop files here</p>
                <p className="text-sm text-seade-gray-dark mb-4">or click to browse</p>
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
                    className="inline-block bg-seade-blue-primary text-white px-6 py-2 rounded cursor-pointer hover:bg-seade-blue-dark transition-colors"
                >
                    Browse Files
                </label>
                <p className="text-xs text-seade-gray-dark mt-4">Supported: PDF, CSV, DOCX</p>
            </div>

            {/* Pending Files */}
            {files.length > 0 && (
                <div className="mb-6">
                    <h3 className="text-lg font-semibold mb-3">Pending Upload:</h3>
                    <div className="space-y-2">
                        {files.map((file, idx) => (
                            <div key={idx} className="flex items-center justify-between bg-gray-50 p-3 rounded">
                                <div className="flex flex-col">
                                    <span className="font-medium">{file.name}</span>
                                    <span className="text-xs text-seade-gray-dark">{formatFileSize(file.size)}</span>
                                </div>
                                <button
                                    onClick={() => removeFile(idx)}
                                    className="text-red-500 hover:text-red-700 p-1"
                                    title="Remove file"
                                >
                                    ✕
                                </button>
                            </div>
                        ))}
                    </div>
                    <button
                        onClick={uploadFiles}
                        disabled={uploading}
                        className="mt-4 bg-seade-blue-primary text-white px-6 py-2 rounded hover:bg-seade-blue-dark disabled:bg-gray-400 transition-colors"
                    >
                        {uploading ? 'Uploading...' : 'Upload Files'}
                    </button>
                </div>
            )}

            {/* Uploaded Files */}
            <div className="mb-6">
                <div className="flex items-center justify-between mb-3">
                    <h3 className="text-lg font-semibold">Uploaded Documents:</h3>
                    {uploadedFiles.length > 0 && (
                        <div className="space-x-2 text-sm">
                            <button onClick={selectAll} className="text-seade-blue-primary hover:underline">Select All</button>
                            <span className="text-seade-gray-medium">|</span>
                            <button onClick={deselectAll} className="text-seade-blue-primary hover:underline">Deselect All</button>
                        </div>
                    )}
                </div>

                {uploadedFiles.length === 0 ? (
                    <p className="text-seade-gray-dark">No documents uploaded yet.</p>
                ) : (
                    <div className="space-y-2 max-h-60 overflow-y-auto pr-2">
                        {uploadedFiles.map((file, idx) => (
                            <div
                                key={idx}
                                className={`flex items-center justify-between p-3 rounded shadow transition-colors cursor-pointer ${selectedFilenames.includes(file.name) ? 'bg-blue-50 border-l-4 border-seade-blue-primary' : 'bg-white'
                                    }`}
                                onClick={() => toggleFileSelection(file.name)}
                            >
                                <div className="flex items-center">
                                    <input
                                        type="checkbox"
                                        checked={selectedFilenames.includes(file.name)}
                                        onChange={() => { }} // Handled by div onClick
                                        className="mr-3 h-4 w-4 text-seade-blue-primary rounded"
                                    />
                                    <span className="font-medium">{file.name}</span>
                                </div>
                                <span className="text-sm text-seade-gray-dark">{formatFileSize(file.size)}</span>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Start Pipeline Button */}
            <button
                onClick={startPipeline}
                disabled={selectedFilenames.length === 0 || (jobStatus && jobStatus.status === 'processing')}
                className="w-full bg-seade-blue-primary text-white px-6 py-3 rounded-lg text-lg font-semibold hover:bg-seade-blue-dark disabled:bg-gray-400 transition-colors shadow-lg"
            >
                {selectedFilenames.length > 0
                    ? `Start Extraction (${selectedFilenames.length} files)`
                    : 'Select files to start extraction'
                }
            </button>

            {/* Job Status */}
            {jobStatus && (
                <div className="mt-6 bg-white p-6 rounded-lg shadow">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-semibold">Pipeline Status</h3>
                        <JobStatusBadge status={jobStatus.status} />
                    </div>

                    <ProgressBar progress={jobStatus.progress || 0} status={jobStatus.status} />

                    {jobStatus.current_stage && (
                        <div className="flex flex-col space-y-1 mb-3">
                            <p className="text-sm text-seade-gray-dark">
                                Current stage: <span className="font-semibold">{jobStatus.current_stage}</span>
                            </p>
                            {jobStatus.usage && (
                                <div className="mt-2 p-3 bg-green-50 rounded border border-green-200 flex justify-between items-center">
                                    <div className="flex flex-col">
                                        <span className="text-xs text-seade-gray-dark uppercase tracking-wider font-semibold">Consumo de Tokens</span>
                                        <span className="text-lg font-mono text-seade-blue-dark">
                                            {(jobStatus.usage.input_tokens + jobStatus.usage.output_tokens).toLocaleString()}
                                        </span>
                                    </div>
                                    <div className="flex flex-col items-end">
                                        <span className="text-xs text-seade-gray-dark uppercase tracking-wider font-semibold">Custo Estimado</span>
                                        <span className="text-xl font-bold text-green-600">
                                            ${jobStatus.usage.total_cost.toFixed(4)}
                                        </span>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {jobStatus.status === 'completed' && (
                        <div className="mt-4">
                            <a
                                href={`/visualize?job=${jobId}`}
                                className="inline-block bg-green-500 text-white px-6 py-2 rounded hover:bg-green-600 transition-colors"
                            >
                                View Knowledge Graph →
                            </a>
                        </div>
                    )}

                    {jobStatus.error && (
                        <div className="mt-4 text-red-600">
                            Error: {jobStatus.error}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default UploadPage;
