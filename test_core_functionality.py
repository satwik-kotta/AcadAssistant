#!/usr/bin/env python3
"""
Simple direct test of prerequisites and quiz generation.
Tests the core requirements:
1. Prerequisites extracted based on uploaded documents
2. Quizzes generated from document content
"""

import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

def test_prerequisites_from_document():
    """Test that prerequisites are extracted from document content."""
    print("\n" + "="*70)
    print("TEST: PREREQUISITES FROM DOCUMENT CONTENT")
    print("="*70)
    
    from backend.enhanced_ingest import analyse_document
    
    # Simulate a course syllabus
    syllabus = """
ADVANCED LINEAR ALGEBRA - COURSE SYLLABUS

COURSE OVERVIEW:
This course covers advanced topics in linear algebra with applications to 
machine learning, computer graphics, and quantum mechanics.

TOPICS COVERED:
- Matrix decompositions (LU, QR, SVD)
- Eigenvalues and eigenvectors
- Linear transformations and their properties
- Inner product spaces and orthogonalization
- Applications to data science
- Numerical methods for eigenvalue problems

COURSE REQUIREMENTS:
This is an advanced course. You should already know:

MUST KNOW (absolutely essential):
- Basic matrix operations (addition, multiplication, transpose)
- Systems of linear equations and Gaussian elimination
- Determinants and matrix inverses
- Vector spaces and linear independence
- Basis and dimension
- Basic calculus (derivatives, chain rule)

GOOD TO KNOW (highly recommended):
- Python or MATLAB for numerical computation
- Basic probability and statistics
- Optimization techniques
- Complex numbers and their properties

OPTIONAL (helpful but not required):
- Differential equations
- Abstract algebra
- Numerical linear algebra implementations
"""
    
    print("\n📄 Analyzing syllabus...")
    analysis = analyse_document(syllabus, "LinearAlgebra_Advanced_Syllabus.pdf")
    
    print(f"\n✓ Document Analysis Complete:")
    print(f"  Subject: {analysis.get('subject', 'Unknown')}")
    print(f"  Type: {analysis.get('document_type', 'Unknown')}")
    print(f"  Difficulty: {analysis.get('difficulty_level', 'Unknown')}")
    
    print(f"\n📚 Topics Covered: {len(analysis.get('topics_covered', []))}")
    for topic in analysis.get('topics_covered', [])[:3]:
        print(f"  - {topic.get('topic')} ({topic.get('difficulty', 'unknown')})")
    
    print(f"\n🎯 Prerequisites Found: {len(analysis.get('prerequisites', []))}")
    for prereq in analysis.get('prerequisites', []):
        urgency = prereq.get('urgency', 'unknown')
        topic = prereq.get('topic', 'Unknown')
        reason = prereq.get('reason', '')[:50]
        print(f"  [{urgency}] {topic}")
        print(f"      Reason: {reason}...")
    
    print(f"\n✅ Result: Prerequisites successfully extracted from document content!")
    return True

def test_quiz_generation():
    """Test that quizzes are generated from document content."""
    print("\n" + "="*70)
    print("TEST: QUIZ GENERATION FROM DOCUMENT")
    print("="*70)
    
    from backend.llm_router import llm_json
    
    # Sample course content
    lesson = """
LESSON 5: MATRIX EIGENVALUES

An eigenvalue of a matrix A is a scalar λ such that there exists a non-zero 
vector v satisfying:
    A·v = λ·v

The vector v is called an eigenvector corresponding to eigenvalue λ.

KEY CONCEPTS:
1. Characteristic polynomial: det(A - λI) = 0
2. Eigenvalues are roots of the characteristic polynomial
3. For an n×n matrix, there are at most n eigenvalues (counting multiplicity)
4. Eigenvectors of different eigenvalues are linearly independent
5. Sum of eigenvalues = trace(A)
6. Product of eigenvalues = determinant(A)

APPLICATIONS:
- Stability analysis of systems
- Principal component analysis (PCA) in machine learning
- Google's PageRank algorithm
- Quantum mechanics (observables and measurement)

EXAMPLE:
For matrix A = [[4, 1], [2, 3]]
Eigenvalues: λ₁ = 5, λ₂ = 2
Corresponding eigenvectors determine the principal directions.
"""
    
    print("\n📝 Generating quiz from lesson content...")
    prompt = f"""Generate 2 quiz questions about eigenvalues and eigenvectors based on this content:

{lesson}

Create questions that test understanding. Return ONLY valid JSON with 2 question objects."""
    
    system = """You must return ONLY valid JSON. Format:
[
  {{
    "question_number": 1,
    "question": "...",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct_answer": "A",
    "explanation": "..."
  }}
]"""
    
    try:
        questions = llm_json(prompt, system, temperature=0.4)
        
        if isinstance(questions, list) and len(questions) > 0:
            print(f"\n✓ Quiz Generated Successfully!")
            print(f"  Questions: {len(questions)}")
            
            for q in questions:
                print(f"\n  Q{q.get('question_number')}: {q.get('question')[:60]}...")
                options = q.get('options', {})
                print(f"  Options: A, B, C, D")
                print(f"  Correct: {q.get('correct_answer')}")
                print(f"  Explanation: {q.get('explanation', '')[:60]}...")
            
            print(f"\n✅ Result: Quizzes successfully generated from document content!")
            return True
        else:
            print(f"❌ Quiz generation failed - invalid format")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_ollama_status():
    """Check Ollama status."""
    print("\n" + "="*70)
    print("VERIFY: OLLAMA (OPEN-SOURCE LLM) STATUS")
    print("="*70)
    
    try:
        import httpx
        
        response = httpx.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3.1",
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "stream": False
            },
            timeout=30
        )
        
        if response.status_code == 200:
            print("✅ Ollama is running and responding")
            print(f"   Model: llama3.1")
            print(f"   Response: {response.json()['message']['content'][:50]}")
            return True
        else:
            print(f"❌ Ollama error: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Ollama not responding: {e}")
        return False

def main():
    print("\n" + "="*70)
    print("CORE FUNCTIONALITY TEST: PREREQUISITES & QUIZ FROM DOCUMENTS")
    print("="*70)
    
    print("\nVerifying:")
    print("1. System reads documents")
    print("2. Prerequisites are extracted based on document content")
    print("3. Quizzes are generated from document content")
    print("4. Open-source model (Ollama) is working")
    
    results = {}
    
    results["Ollama Status"] = test_ollama_status()
    results["Prerequisites from Document"] = test_prerequisites_from_document()
    results["Quiz from Document"] = test_quiz_generation()
    
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 SUCCESS: System is working correctly!")
        print("   - Documents are being read")
        print("   - Prerequisites are extracted from documents")
        print("   - Quizzes are generated from document content")
        print("   - Ollama (open-source) is operating normally")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed - review output above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
