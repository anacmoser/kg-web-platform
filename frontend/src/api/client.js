// API client for backend communication
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:5000/api/v1';

class APIClient {
    async uploadDocument(file, onProgress) {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`${API_BASE_URL}/documents/upload`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Upload failed');
        }

        return response.json();
    }

    async listDocuments() {
        const response = await fetch(`${API_BASE_URL}/documents/`);
        if (!response.ok) throw new Error('Failed to fetch documents');
        return response.json();
    }

    async startPipeline(filenames, config = {}) {
        const response = await fetch(`${API_BASE_URL}/pipeline/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filenames, config }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Pipeline start failed');
        }

        return response.json();
    }

    async getJobStatus(jobId) {
        const response = await fetch(`${API_BASE_URL}/pipeline/status/${jobId}`);
        if (!response.ok) throw new Error('Failed to fetch job status');
        return response.json();
    }

    async getGraph(jobId) {
        const response = await fetch(`${API_BASE_URL}/graphs/${jobId}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to fetch graph');
        }
        return response.json();
    }

    async getOntology(jobId) {
        const response = await fetch(`${API_BASE_URL}/ontology/${jobId}`);
        if (!response.ok) throw new Error('Failed to fetch ontology');
        return response.json();
    }
}

export const api = new APIClient();
