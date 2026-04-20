#!/usr/bin/env python3
"""
Comprehensive test of the document processing pipeline.
Tests:
1. Ollama connectivity
2. Document reading & text extraction
3. Prerequisite extraction from documents
4. Quiz generation from documents
"""

import sys
import os
import json
import httpx
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

def print_section(title):
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80)

def test_ollama_connection():
    """Test if Ollama is running and responding."""
    print_section("TEST 1: Ollama Server Connection")
    
    try:
        response = httpx.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3.1",
                "messages": [{"role": "user", "content": "Say 'OK'"}],
                "stream": False
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Ollama is running and responding")
            print(f"   Model: llama3.1")
            print(f"   Response: {result['message']['content'][:100]}")
            return True
        else:
            print(f"❌ Ollama returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cannot connect to Ollama: {e}")
        return False

def test_document_ingestion():
    """Test document parsing and text extraction."""
    print_section("TEST 2: Document Ingestion")
    
    try:
        from backend.enhanced_ingest import EnhancedPDFParser
        
        # Check if sample document exists
        sample_docs = list(Path("uploads").glob("*.pdf")) if Path("uploads").exists() else []
        
        if not sample_docs:
            print("⚠️  No sample documents in uploads/ folder")
            print("   (This is OK - documents would be uploaded by users)")
            return None
        
        parser = EnhancedPDFParser()
        doc_path = sample_docs[0]
        print(f"Testing with: {doc_path.name}")
        
        result = parser.parse_document(str(doc_path))
        
        full_text = result.get("full_text", "")
        text_chunks = result.get("text_chunks", [])
        
        print(f"✅ Document parsed successfully")
        print(f"   Full text length: {len(full_text)} chars")
        print(f"   Chunks: {len(text_chunks)}")
        print(f"   Sample text: {full_text[:150]}...")
        
        if full_text:
            return {"text": full_text, "chunks": text_chunks}
        else:
            print("❌ Document has no extracted text")
            return False
            
    except Exception as e:
        print(f"❌ Document ingestion failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_prerequisite_extraction():
    """Test prerequisite extraction from document content."""
    print_section("TEST 3: Prerequisite Extraction")
    
    try:
        from backend.enhanced_ingest import analyse_document
        from backend.llm_router import llm_json
        
        # Create a sample document snippet
        sample_text = """
        CALCULUS I - COURSE SYLLABUS
        
        Topics Covered:
        - Limits and continuity
        - Derivatives and their applications
        - Integration methods
        - Series and sequences
        
        Prerequisites:
        - Strong background in algebra (solving equations, factoring, working with polynomials)
        - Trigonometry (sine, cosine, tangent functions and their properties)
        - Understanding of functions and graphs
        - Exponents and logarithms
        
        This course builds on the mathematical foundation you should have from algebra and 
        trigonometry courses. If you struggle with these topics, you should review them first.
        """
        
        print("Testing prerequisite extraction with sample text...")
        print(f"Input: {len(sample_text)} characters")
        
        analysis = analyse_document(sample_text, "test_calculus_syllabus.pdf")
        
        print(f"✅ Document analysis completed")
        print(f"   Subject: {analysis.get('subject', 'unknown')}")
        print(f"   Type: {analysis.get('document_type', 'unknown')}")
        print(f"   Difficulty: {analysis.get('difficulty_level', 'unknown')}")
        print(f"   Topics covered: {len(analysis.get('topics_covered', []))}")
        print(f"   Prerequisites found: {len(analysis.get('prerequisites', []))}")
        
        if analysis.get('prerequisites'):
            print("\n   ✓ Prerequisites extracted:")
            for prereq in analysis['prerequisites'][:2]:
                print(f"     - {prereq.get('topic')} ({prereq.get('urgency')})")
                print(f"       Reason: {prereq.get('reason')[:80]}...")
        
        return analysis
        
    except Exception as e:
        print(f"❌ Prerequisite extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_quiz_generation():
    """Test quiz generation from document content."""
    print_section("TEST 4: Quiz Generation")
    
    try:
        from backend.llm_router import llm_json
        
        # Create a sample document for quiz
        sample_doc = """
        CHAPTER 3: THE DERIVATIVE
        
        The derivative of a function f(x) at a point x is defined as the limit:
        
        f'(x) = lim(h→0) [f(x+h) - f(x)] / h
        
        This represents the instantaneous rate of change of the function at that point.
        
        Key Properties:
        1. Power Rule: d/dx[x^n] = n*x^(n-1)
        2. Sum Rule: d/dx[f(x) + g(x)] = f'(x) + g'(x)
        3. Product Rule: d/dx[f(x)*g(x)] = f'(x)*g(x) + f(x)*g'(x)
        4. Chain Rule: d/dx[f(g(x))] = f'(g(x)) * g'(x)
        
        Applications:
        - Finding critical points
        - Optimization problems
        - Related rates problems
        - Motion and velocity
        """
        
        print("Testing quiz generation with sample content...")
        print(f"Input: {len(sample_doc)} characters")
        
        prompt = f"""Generate 3 multiple choice questions that test understanding of the derivative.

Document content:
{sample_doc}

Rules:
1. Each question must be directly based on the document content
2. Each question must have exactly 4 options labeled A, B, C, D
3. Only one option must be correct
4. Wrong options must be plausible but clearly incorrect

Return ONLY a JSON array with exactly 3 objects in this format:
[
  {{
    "question_number": 1,
    "question": "the question text",
    "options": {{
      "A": "first option",
      "B": "second option",
      "C": "third option",
      "D": "fourth option"
    }},
    "correct_answer": "A",
    "explanation": "why this answer is correct, referencing the document"
  }}
]"""
        
        system = "You are an expert teacher creating quiz questions. Return ONLY valid JSON. No markdown, no explanation."
        
        questions = llm_json(prompt, system, temperature=0.4)
        
        if isinstance(questions, list) and len(questions) > 0:
            print(f"✅ Quiz generated successfully")
            print(f"   Questions generated: {len(questions)}")
            
            for q in questions[:1]:
                print(f"\n   Question {q.get('question_number')}:")
                print(f"   {q.get('question')[:100]}...")
                print(f"   Options: A, B, C, D available")
                print(f"   Correct: {q.get('correct_answer')}")
            
            return questions
        else:
            print(f"❌ Quiz generation returned invalid format")
            return False
            
    except Exception as e:
        print(f"❌ Quiz generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_llm_json_parsing():
    """Test JSON parsing from LLM responses."""
    print_section("TEST 5: LLM JSON Parsing")
    
    try:
        from backend.llm_router import llm_json
        
        print("Testing JSON parsing with structured output...")
        
        prompt = """Create a simple JSON object with:
        - name: "Test Subject"
        - topics: array of 2 topic strings
        - difficulty: one of ["easy", "medium", "hard"]
        """
        
        system = "Return ONLY valid JSON. No markdown, no explanation."
        
        result = llm_json(prompt, system, temperature=0.1)
        
        if isinstance(result, dict):
            print(f"✅ JSON parsing successful")
            print(f"   Result type: {type(result).__name__}")
            print(f"   Content: {json.dumps(result, indent=2)[:200]}")
            return True
        else:
            print(f"❌ JSON parsing returned non-dict: {type(result)}")
            return False
            
    except Exception as e:
        print(f"❌ JSON parsing failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_database_operations():
    """Test document storage in database."""
    print_section("TEST 6: Database Document Storage")
    
    try:
        from backend.models import Session, Document as DocModel
        
        db_session = Session()
        
        # Try to query existing documents
        docs = db_session.query(DocModel).all()
        db_session.close()
        
        print(f"✅ Database connection successful")
        print(f"   Documents in database: {len(docs)}")
        
        if docs:
            doc = docs[0]
            print(f"\n   Sample document:")
            print(f"   - Filename: {doc.filename}")
            print(f"   - Type: {doc.doc_type}")
            print(f"   - Chunks: {doc.num_chunks}")
            print(f"   - Full text: {len(doc.full_text) if doc.full_text else 0} chars")
            print(f"   - Analysis: {'✓' if doc.analysis_json else '✗'}")
        
        return True
        
    except Exception as e:
        print(f"❌ Database query failed: {e}")
        return False

def main():
    print("\n" + "="*80)
    print("  DOCUMENT PROCESSING PIPELINE TEST SUITE")
    print("="*80)
    
    print("\nThis test suite verifies:")
    print("1. Ollama (open-source LLM) is running and working")
    print("2. Document text extraction is working")
    print("3. Prerequisite extraction from documents works")
    print("4. Quiz generation from documents works")
    print("5. LLM JSON parsing works correctly")
    print("6. Database document storage is working")
    
    results = {}
    
    # Run tests
    results["Ollama Connection"] = test_ollama_connection()
    results["LLM JSON Parsing"] = test_llm_json_parsing()
    results["Document Ingestion"] = test_document_ingestion()
    results["Prerequisite Extraction"] = test_prerequisite_extraction()
    results["Quiz Generation"] = test_quiz_generation()
    results["Database Operations"] = test_database_operations()
    
    # Summary
    print_section("TEST SUMMARY")
    
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    for test_name, result in results.items():
        if result is None:
            status = "⏭️  SKIPPED"
        elif result is True or (isinstance(result, dict) and result):
            status = "✅ PASS"
        else:
            status = "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n   Total: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed == 0:
        print("\n✅ ALL CORE TESTS PASSED")
        print("\nSystem is ready!")
        print("- Ollama is running")
        print("- Document parsing works")
        print("- Prerequisites can be extracted")
        print("- Quizzes can be generated")
        return 0
    else:
        print(f"\n❌ {failed} TEST(S) FAILED - See details above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
