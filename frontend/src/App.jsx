import React from 'react';
import { Route, Switch } from "wouter";
import UploadPage from './pages/UploadPage';
import VisualizePage from './pages/VisualizePage';
import OntologyPage from './pages/OntologyPage';

// Home page
const Home = () => (
    <div className="p-8">
        <h1 className="text-3xl mb-4">SGKG - Sistema Gestor de Knowledge Graphs</h1>
        <div className="bg-white p-6 rounded-lg shadow-md border-t-4 border-seade-blue-primary">
            <p className="text-lg mb-4">Bem-vindo à plataforma de gestão de conhecimento.</p>
            <p className="mb-4">Transform heterogeneous documents (PDF, CSV, DOCX) into interactive knowledge graphs.</p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
                <a href="/upload" className="block p-6 bg-seade-blue-light text-white rounded-lg hover:bg-seade-blue-primary transition-colors">
                    <div className="text-4xl mb-2">📤</div>
                    <h3 className="font-bold text-lg">Upload Documents</h3>
                    <p className="text-sm mt-2">Upload PDF, CSV, or DOCX files to extract knowledge</p>
                </a>

                <a href="/visualize" className="block p-6 bg-seade-blue-light text-white rounded-lg hover:bg-seade-blue-primary transition-colors">
                    <div className="text-4xl mb-2">🔍</div>
                    <h3 className="font-bold text-lg">Visualize Graphs</h3>
                    <p className="text-sm mt-2">Explore interactive knowledge graph visualizations</p>
                </a>

                <a href="/ontology" className="block p-6 bg-seade-blue-light text-white rounded-lg hover:bg-seade-blue-primary transition-colors">
                    <div className="text-4xl mb-2">🧠</div>
                    <h3 className="font-bold text-lg">View Ontology</h3>
                    <p className="text-sm mt-2">Review entity types and relation schemas</p>
                </a>
            </div>
        </div>
    </div>
);

function App() {
    return (
        <div className="min-h-screen bg-seade-gray-light">
            <nav className="bg-seade-blue-dark text-white p-4 shadow-lg">
                <div className="container mx-auto flex justify-between items-center">
                    <div className="text-xl font-bold">SGKG Platform</div>
                    <div className="space-x-4">
                        <a href="/" className="hover:text-seade-blue-light">Home</a>
                        <a href="/upload" className="hover:text-seade-blue-light">Upload</a>
                        <a href="/visualize" className="hover:text-seade-blue-light">Visualize</a>
                        <a href="/ontology" className="hover:text-seade-blue-light">Ontology</a>
                    </div>
                </div>
            </nav>

            <main>
                <Switch>
                    <Route path="/" component={Home} />
                    <Route path="/upload" component={UploadPage} />
                    <Route path="/visualize" component={VisualizePage} />
                    <Route path="/ontology" component={OntologyPage} />
                    <Route>404: Page Not Found</Route>
                </Switch>
            </main>
        </div>
    );
}

export default App;
