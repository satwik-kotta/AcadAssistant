#!/usr/bin/env python
"""
Validation script for enhanced document parsing system.
Tests all major components and provides setup recommendations.
"""

import sys
import os
import importlib
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all required modules can be imported."""
    print("🔍 Testing imports...")
    
    tests = {
        "pdfplumber": "PDF parsing with table support",
        "langchain_community.vectorstores": "Vector storage",
        "langchain_text_splitters": "Text splitting",
        "google.generativeai": "Google Generative AI",
        "sqlalchemy": "Database ORM",
    }
    
    optional = {
        "pytesseract": "OCR support (optional)",
        "PIL": "Image processing (for OCR)",
    }
    
    results = []
    
    for module, description in tests.items():
        try:
            importlib.import_module(module)
            results.append((module, "✅", description))
        except ImportError as e:
            results.append((module, "❌", f"{description} - {e}"))
        except Exception as e:
            results.append((module, "❌", f"{description} - {e}"))
    
    print("\n📦 Required Dependencies:")
    for module, status, desc in results:
        print(f"  {status} {module}: {desc}")
    
    print("\n📦 Optional Dependencies:")
    for module, desc in optional.items():
        try:
            __import__(module)
            print(f"  ✅ {module}: {desc}")
        except ImportError:
            print(f"  ⚠️  {module}: {desc} [NOT INSTALLED]")
    
    required_failed = [r for r in results if r[1] == "❌"]
    if required_failed:
        print(f"\n❌ {len(required_failed)} required dependency/dependencies missing!")
        return False
    
    return True


def test_backend_modules():
    """Test that backend modules can be imported."""
    print("\n🔍 Testing backend modules...")
    
    modules = [
        "backend.enhanced_ingest",
        "backend.enhanced_retriever",
        "backend.models",
        "backend.embeddings_provider",
    ]
    
    all_ok = True
    for module in modules:
        try:
            __import__(module)
            print(f"  ✅ {module}")
        except ImportError as e:
            print(f"  ❌ {module}: {e}")
            all_ok = False
    
    return all_ok


def test_database():
    """Test database connectivity and schema."""
    print("\n🔍 Testing database...")
    
    try:
        from backend.models import engine, Base, Document, DocumentChunk
        
        # Test connection
        with engine.connect() as conn:
            print("  ✅ Database connection OK")
        
        # Check tables
        inspector = __import__('sqlalchemy').inspect(engine)
        tables = inspector.get_table_names()
        
        required_tables = ["documents", "document_chunks"]
        for table in required_tables:
            if table in tables:
                print(f"  ✅ Table '{table}' exists")
            else:
                print(f"  ⚠️  Table '{table}' not found (will be created on first run)")
        
        return True
    except Exception as e:
        print(f"  ❌ Database error: {e}")
        return False


def test_embeddings():
    """Test embeddings provider (requires API key)."""
    print("\n🔍 Testing embeddings provider...")
    
    try:
        from backend.embeddings_provider import get_embeddings
        embeddings = get_embeddings()
        print(f"  ✅ Embeddings provider initialized")
        provider_name = embeddings.__class__.__name__
        model_name = getattr(embeddings, "model", None)
        if model_name:
            print(f"     Provider: {provider_name}, model: {model_name}")
        else:
            print(f"     Provider: {provider_name}")
        return True
    except Exception as e:
        print(f"  ⚠️  Embeddings provider: {e}")
        print(f"     This is expected if API keys aren't configured")
        return False


def test_vectorstore():
    """Check vectorstore path."""
    print("\n🔍 Checking vectorstore path...")
    
    vectorstore_path = "vectorstore/index"
    
    if os.path.exists(vectorstore_path):
        files = os.listdir(vectorstore_path)
        print(f"  ✅ Vectorstore exists with {len(files)} files")
    else:
        print(f"  ℹ️  Vectorstore not yet created (will be created on first document upload)")
    
    # Check if directory is writable
    parent_dir = os.path.dirname(vectorstore_path) or "."
    if os.access(parent_dir, os.W_OK):
        print(f"  ✅ Vectorstore directory is writable")
        return True
    else:
        print(f"  ❌ Vectorstore directory is not writable")
        return False


def test_api_routes():
    """Check API routes are available."""
    print("\n🔍 Checking API routes...")
    
    try:
        from backend.api import app
        
        routes = [
            "/upload",
            "/documents",
            "/plan",
            "/feedback",
            "/chat",
        ]
        
        # Get FastAPI routes
        api_routes = [route.path for route in app.routes]
        
        for route in routes:
            if route in api_routes:
                print(f"  ✅ {route}")
            else:
                print(f"  ⚠️  {route} not found")
        
        print(f"  ℹ️  Total routes: {len(api_routes)}")
        return True
    except Exception as e:
        print(f"  ❌ Error checking routes: {e}")
        return False


def check_tesseract():
    """Check if Tesseract OCR is installed."""
    print("\n🔍 Checking Tesseract OCR...")
    
    try:
        import pytesseract
        try:
            # Try to call tesseract
            pytesseract.get_tesseract_version()
            print("  ✅ Tesseract is installed and working")
            return True
        except Exception as e:
            print(f"  ⚠️  Tesseract not found: {e}")
            print(f"     Install with: brew install tesseract (macOS) or apt-get install tesseract-ocr (Linux)")
            return False
    except ImportError:
        print("  ⚠️  pytesseract not installed (OCR support disabled)")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("  Enhanced Document Parsing System - Validation")
    print("=" * 60)
    
    results = {
        "Imports": test_imports(),
        "Backend Modules": test_backend_modules(),
        "Database": test_database(),
        "Embeddings": test_embeddings(),
        "Vectorstore": test_vectorstore(),
        "API Routes": test_api_routes(),
        "Tesseract OCR": check_tesseract(),
    }
    
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "⚠️  PARTIAL"
        print(f"  {status}: {test_name}")
    
    critical = ["Imports", "Backend Modules", "Database", "Vectorstore"]
    critical_passed = all(results.get(t, False) for t in critical)
    
    if critical_passed:
        print("\n✅ System is ready!")
        print("\nNext steps:")
        print("  1. Start the backend: python -m backend.api")
        print("  2. Upload a document: curl -F 'file=@example.pdf' http://localhost:8000/upload")
        print("  3. View documents: curl http://localhost:8000/documents")
        print("\nSee ENHANCED_PARSING_GUIDE.md for full documentation")
        return 0
    else:
        print("\n❌ System needs fixes before use")
        print("\nSee ENHANCED_PARSING_GUIDE.md for troubleshooting")
        return 1


if __name__ == "__main__":
    sys.exit(main())
