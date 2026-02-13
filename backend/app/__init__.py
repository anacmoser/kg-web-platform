from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from app.config import settings
from app.api.routes import documents, pipeline, graphs, ontology, nadia

socketio = SocketIO()

def create_app():
    app = Flask(__name__)
    
    # Configuration
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["UPLOAD_FOLDER"] = settings.UPLOAD_DIR
    
    # Middleware
    CORS(app, resources={r"/api/*": {"origins": settings.cors_origins_list}})
    
    # Blueprints
    app.register_blueprint(documents.bp, url_prefix=f"{settings.API_V1_STR}/documents")
    app.register_blueprint(pipeline.bp, url_prefix=f"{settings.API_V1_STR}/pipeline")
    app.register_blueprint(graphs.bp, url_prefix=f"{settings.API_V1_STR}/graphs")
    app.register_blueprint(ontology.bp, url_prefix=f"{settings.API_V1_STR}/ontology")
    app.register_blueprint(nadia.bp, url_prefix=f"{settings.API_V1_STR}/nadia")
    
    # Extensions
    socketio.init_app(app, cors_allowed_origins=settings.cors_origins_list)
    
    @app.route("/health")
    def health_check():
        return {"status": "ok", "version": "0.1.0"}
        
    return app
