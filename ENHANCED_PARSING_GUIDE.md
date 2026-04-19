# Enhanced Document Parsing System

## Overview

The document parsing system has been significantly enhanced to overcome limitations of basic RAG. These improvements enable better handling of complex academic documents.

## What's New

### 1. **Structure Preservation**
- **Hierarchical Chunking**: Documents are now chunked by semantic units (sections, paragraphs) instead of fixed character counts
- **Section Tracking**: Each chunk remembers its section title and page number
- **Metadata Preservation**: Document metadata (title, author, date, page count) is extracted and stored

### 2. **Table & Complex Content Support**
- **Table Extraction**: Tables are extracted separately and formatted as readable markdown
- **Multi-column Detection**: pdfplumber intelligently handles multi-column layouts
- **Image Detection**: System notes which pages contain images for reference

### 3. **OCR Support for Scanned PDFs**
- **Automatic OCR Fallback**: If text extraction yields very little content, the system automatically runs OCR
- **Pytesseract Integration**: Uses Tesseract OCR engine (must be installed separately on your system)
- **Graceful Degradation**: Falls back to basic text if OCR unavailable

### 4. **Document Management**
- **Document Tracking**: All uploaded documents are tracked in the database
- **Document Listing**: `GET /documents` - View all uploaded documents with metadata
- **Document Deletion**: `DELETE /documents/{id}` - Remove documents and rebuild vectorstore
- **Document Summaries**: View document structure, sections, content types

### 5. **Improved Retrieval**
- **Source Attribution**: Retrieved chunks now show their source file, page, and section
- **Relevance Scoring**: Each retrieved chunk includes a relevance score (0-1)
- **Hybrid Retrieval**: Multi-step filtering for higher-quality results
- **Chunk Metadata**: Full tracking of which chunks came from which documents

## Installation

### Prerequisites

```bash
# Update requirements (includes new dependencies)
pip install -r requirements.txt
```

### Optional: OCR Support

For scanned PDF support, install Tesseract:

**macOS:**
```bash
brew install tesseract
export PYTESSERACT_PATH=$(which tesseract)
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install tesseract-ocr
```

**Windows:**
Download from: https://github.com/UB-Mannheim/tesseract/wiki

After installation, pytesseract will automatically detect it.

## API Changes

### New/Updated Endpoints

#### Upload Document (Enhanced)
```bash
POST /upload
```
**Response now includes:**
- `document_id`: Unique ID for the document
- `doc_type`: Auto-detected type (syllabus, notes, assignment, research_paper, unknown)
- Detailed error messages if parsing fails

**Auto-detection based on filename:**
- "syllabus" → syllabus type
- "assignment" or "rubric" → assignment type
- "notes" or "lecture" → notes type
- "research" or "paper" → research_paper type

#### List Documents
```bash
GET /documents
```
**Response:**
```json
{
  "documents": [
    {
      "id": 1,
      "filename": "CS101_Syllabus.pdf",
      "file_size": 245000,
      "num_pages": 5,
      "num_chunks": 12,
      "doc_type": "syllabus",
      "has_tables": true,
      "has_images": false,
      "created_at": "2026-04-17T10:30:00"
    }
  ],
  "total": 1
}
```

#### Delete Document
```bash
DELETE /documents/{doc_id}
```
Removes document and automatically rebuilds vectorstore.

### Enhanced Retrieval (Internal)

```python
# Basic retrieval (unchanged)
context = retrieve_context(query, k=5)

# With source attribution
result = retrieve_context_with_sources(query, k=5)
# Returns: {"context": "...", "sources": [...]}

# Hybrid retrieval with filtering
result = retrieve_context_hybrid(query, k=5)
# Returns: {"context": "...", "sources": [...], "chunks": [...]}
```

## Database Schema

### New Tables

**documents** table:
```
id (int, primary key)
user_id (str)
filename (str)
file_path (str)
file_size (int)
num_pages (int)
num_chunks (int)
doc_type (str): syllabus | notes | assignment | research_paper | unknown
has_tables (bool)
has_images (bool)
created_at (datetime)
updated_at (datetime)
```

**document_chunks** table:
```
id (int, primary key)
document_id (int, foreign key)
chunk_index (int)
page_number (int)
section_title (str)
content_preview (str) - first 200 chars
chunk_type (str): text | table | image_caption | ocr_text
relevance_score (float, nullable)
created_at (datetime)
```

## Migration from Old System

If you have existing documents indexed:

1. **Option A: Keep & Continue** (No action needed)
   - Old vectorstore continues to work
   - Old `ingest_document()` function delegates to new system
   - New uploads use enhanced parsing

2. **Option B: Rebuild Vectorstore** (Recommended for better results)
   - Delete current `vectorstore/` directory
   - Re-upload documents through `/upload` endpoint
   - New system will parse with full enhancements

```bash
# Backup first
mv vectorstore vectorstore.backup

# Then re-upload your documents
curl -X POST -F "file=@path/to/syllabus.pdf" http://localhost:8000/upload
```

## Usage Examples

### Upload with Auto-Detection
```bash
curl -X POST -F "file=@CS101_Syllabus.pdf" http://localhost:8000/upload
# Response automatically detects "syllabus" type from filename
```

### List All Documents
```bash
curl http://localhost:8000/documents
```

### Delete Outdated Document
```bash
curl -X DELETE http://localhost:8000/documents/3
```

### Agent Query with Sources (Backend)
```python
from backend.enhanced_retriever import retrieve_with_sources

result = retrieve_with_sources("What's the deadline for project 1?", k=5)

# Access sources
for source in result["sources"]:
    print(f"Found in: {source['filename']} (pg {source['page']})")
    print(f"Relevance: {source['relevance_score']:.2%}")
```

## Advanced Configuration

### Chunking Parameters
Edit `EnhancedPDFParser` initialization in `enhanced_ingest.py`:
```python
parser = EnhancedPDFParser(
    max_chunk_size=1000,      # Characters per chunk
    chunk_overlap=150,        # Overlap between chunks
)
```

### Retrieval Filtering
Edit `hybrid_retrieve()` in `enhanced_retriever.py`:
```python
threshold = 0.5  # Only keep chunks with relevance > 50%
k *= 2           # Initially retrieve more, then filter
```

## Limitations & Known Issues

1. **OCR Dependency**: Full OCR support requires Tesseract installation
2. **Memory**: Large PDFs (200+ pages) may require significant memory for processing
3. **FAISS Rebuild**: Deleting documents requires full vectorstore rebuild (scales with document count)
4. **Embedding Model**: Changing embedding model requires vectorstore rebuild

## Performance Notes

- **Document Upload Time**: ~2-5 seconds for 50-page document (with OCR fallback)
- **Retrieval Time**: ~100-200ms for semantic search
- **Storage**: ~1KB per chunk in vectorstore + ~500B per document in database
- **OCR Processing**: ~30-60 seconds for 50-page scanned PDF

## Troubleshooting

### "No readable content found in PDF"
- Document may be completely scanned with no OCR support
- Ensure Tesseract is installed: `which tesseract`
- Try manually with OCR: `python -c "from backend.enhanced_ingest import EnhancedPDFParser; parser = EnhancedPDFParser(); parser.parse_document('your.pdf')"`

### Vectorstore becomes incompatible
- This happens if OpenAI embedding model changes
- System automatically rebuilds, but re-upload documents for consistency:
  ```bash
  curl http://localhost:8000/documents
  # Note the doc_ids, then delete and re-upload
  ```

### Low retrieval quality for questions
- Use hybrid retrieval which filters low-relevance results
- Ensure your questions match document terminology
- Check document type is correctly detected: `GET /documents`

## Future Enhancements

Potential future improvements:
- [ ] Citation/reference extraction
- [ ] Hierarchical indexing (remember section relationships)
- [ ] Custom chunking per document type
- [ ] Parallel document processing
- [ ] Document versioning/change tracking
- [ ] Batch OCR processing
- [ ] Integration with Google Drive/Classroom
