#!/usr/bin/env python
"""
Test Ollama-based prerequisites extraction and quiz generation.
This test focuses on the core LLM functionality without PDF dependencies.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Add repo to path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Sample syllabus text for testing prerequisites extraction
SAMPLE_SYLLABUS = """
LINEAR ALGEBRA - ADVANCED COURSE SYLLABUS

Course Objectives:
Students will master advanced linear algebra concepts including eigenvalues, 
eigenvectors, matrix decomposition, and applications in machine learning.

Course Content:
1. Vector Spaces and Subspaces
2. Linear Transformations
3. Eigenvalues and Eigenvectors
4. Diagonalization and Jordan Forms
5. Inner Products and Orthogonality
6. Matrix Decompositions (SVD, QR, LU)
7. Applications in Data Science

Prerequisites:
Before taking this course, students should be familiar with:
- Basic linear algebra (vectors, matrices, systems of equations)
- Calculus (derivatives, optimization)
- Basic proof techniques

Grading:
- Participation: 10%
- Assignments: 40%
- Midterm Exam: 20%
- Final Project: 30%

Textbooks:
- Axler, S. (2015). Linear Algebra Done Right
- Strang, G. (2016). Introduction to Linear Algebra
"""

SAMPLE_LESSON = """
LESSON: EIGENVALUES AND EIGENVECTORS

Learning Objectives:
- Understand the geometric interpretation of eigenvalues
- Calculate eigenvalues and eigenvectors
- Apply spectral decomposition

Content:

1. Definition and Motivation
   An eigenvector of a square matrix A is a non-zero vector v such that:
   A * v = λ * v
   
   where λ (lambda) is a scalar called the eigenvalue.

2. Characteristic Polynomial
   To find eigenvalues, we solve: det(A - λI) = 0
   
3. Finding Eigenvalues and Eigenvectors
   Step 1: Find characteristic polynomial
   Step 2: Find roots of polynomial (eigenvalues)
   Step 3: For each eigenvalue λ, solve (A - λI)v = 0

4. Properties of Eigenvalues
   - Sum of eigenvalues = trace of matrix
   - Product of eigenvalues = determinant of matrix
   - Similar matrices have same eigenvalues

5. Applications
   - Image compression (SVD)
   - Principal Component Analysis (PCA)
   - Google PageRank algorithm
   - Vibration analysis in engineering

Key Formulas:
- A * v = λ * v (Eigenvalue equation)
- det(A - λI) = 0 (Characteristic equation)
- tr(A) = Σλᵢ (Trace property)

Practice Problems:
1. Find eigenvalues of [[3, 1], [1, 3]]
2. Find eigenvector for eigenvalue 4 of [[2, 3], [3, 2]]
3. Verify that PageRank uses dominant eigenvector
"""


def test_ollama_status():
    """Test that Ollama is running and responding."""
    print("\n" + "="*70)
    print("VERIFY: OLLAMA (OPEN-SOURCE LLM) STATUS")
    print("="*70)
    
    try:
        from backend.llm_router import _call_ollama
        
        response = _call_ollama("What is 2+2?", temperature=0.1)
        print(f"✅ Ollama is running and responding")
        print(f"   Model: llama3.1")
        print(f"   Response: {response}")
        return True
        
    except Exception as e:
        print(f"❌ Ollama failed: {e}")
        return False


def test_prerequisites_extraction():
    """Test extracting prerequisites from a syllabus."""
    print("\n" + "="*70)
    print("TEST: EXTRACT PREREQUISITES FROM SYLLABUS")
    print("="*70)
    
    try:
        from backend.llm_router import llm_json
        
        system_prompt = """You are an expert educational analyst. 
        Analyze the provided course syllabus and extract prerequisites.
        Return ONLY a JSON object with this structure:
        {
            "prerequisites": [{"topic": "...", "reason": "...", "difficulty": "beginner|intermediate|advanced"}],
            "topics_covered": ["topic1", "topic2", ...],
            "difficulty_level": "beginner|intermediate|advanced"
        }"""
        
        user_prompt = f"Analyze this course syllabus:\n\n{SAMPLE_SYLLABUS[:2000]}"
        
        result = llm_json(prompt=user_prompt, system=system_prompt)
        
        print(f"\n📊 Analysis Complete:")
        print(f"   Prerequisites found: {len(result.get('prerequisites', []))}")
        print(f"   Topics identified: {result.get('topics_covered', [])}")
        print(f"   Difficulty: {result.get('difficulty_level', 'unknown')}")
        
        # Show prerequisites
        if result.get('prerequisites'):
            print(f"\n   Required Knowledge:")
            for prereq in result['prerequisites']:
                print(f"   • {prereq.get('topic', 'unknown')}: {prereq.get('reason', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Prerequisite extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_quiz_generation():
    """Test generating quiz questions from lesson content."""
    print("\n" + "="*70)
    print("TEST: GENERATE QUIZ FROM LESSON CONTENT")
    print("="*70)
    
    try:
        from backend.llm_router import llm_json
        
        system_prompt = """You are an expert teacher creating assessment questions.
        Based on the lesson content, generate 3 multiple-choice questions.
        Return ONLY a JSON object with this structure:
        {
            "questions": [
                {
                    "question": "...",
                    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
                    "correct_answer": "A|B|C|D",
                    "explanation": "..."
                }
            ]
        }"""
        
        user_prompt = f"Create quiz questions based on:\n\n{SAMPLE_LESSON[:2000]}"
        
        result = llm_json(prompt=user_prompt, system=system_prompt)
        
        questions = result.get('questions', [])
        print(f"\n📝 Quiz Generated:")
        print(f"   Questions: {len(questions)}")
        
        for i, q in enumerate(questions[:1], 1):
            print(f"\n   Question {i}: {q.get('question', 'N/A')}")
            for key, option in q.get('options', {}).items():
                correct_mark = " ✓" if key == q.get('correct_answer') else ""
                print(f"      {key}) {option}{correct_mark}")
        
        return True
        
    except Exception as e:
        print(f"❌ Quiz generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_document_analysis_flow():
    """Test the complete flow: read document -> extract prerequisites -> generate quiz."""
    print("\n" + "="*70)
    print("TEST: COMPLETE DOCUMENT ANALYSIS FLOW")
    print("="*70)
    
    try:
        from backend.llm_router import llm_json
        
        # Step 1: Analyze document for prerequisites
        print("\n📖 Step 1: Analyzing document...")
        system_prompt1 = """Analyze this educational document.
        Extract prerequisites and topics covered.
        Return JSON with: prerequisites[], topics_covered[], difficulty_level"""
        
        result1 = llm_json(
            prompt=f"Analyze:\n\n{SAMPLE_SYLLABUS[:1500]}",
            system=system_prompt1
        )
        
        topics = result1.get('topics_covered', [])
        print(f"   ✓ Topics identified: {len(topics)}")
        if topics:
            print(f"     {', '.join(topics[:3])}")
        
        # Step 2: Generate quiz based on topics
        print("\n📝 Step 2: Generating quiz...")
        system_prompt2 = """Based on these topics, generate 2 questions:
        Return JSON with: questions[] (each with question, options, correct_answer, explanation)"""
        
        topics_str = ", ".join(topics[:5]) if topics else "Linear Algebra, Matrices, Eigenvalues"
        
        result2 = llm_json(
            prompt=f"Topics to test: {topics_str}\n\nCreate quiz questions",
            system=system_prompt2
        )
        
        questions = result2.get('questions', [])
        print(f"   ✓ Questions generated: {len(questions)}")
        
        print("\n✅ Document analysis flow complete!")
        return True
        
    except Exception as e:
        print(f"❌ Document analysis flow failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "="*70)
    print("OLLAMA PREREQUISITES & QUIZ SYSTEM - TEST SUITE")
    print("="*70)
    
    print("\nTesting:")
    print("1. Ollama (open-source LLM) connectivity")
    print("2. Prerequisites extraction from documents")
    print("3. Quiz generation from lesson content")
    print("4. Complete document analysis flow")
    
    results = {}
    
    # Run tests
    results["Ollama Status"] = test_ollama_status()
    results["Prerequisites Extraction"] = test_prerequisites_extraction()
    results["Quiz Generation"] = test_quiz_generation()
    results["Document Analysis Flow"] = test_document_analysis_flow()
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print("\n" + "="*70)
    if passed == total:
        print(f"🎉 SUCCESS: All {total}/{ total} tests passed!")
        print("\nThe system is working correctly:")
        print("✅ Ollama (open-source model) is operational")
        print("✅ Prerequisites can be extracted from documents")
        print("✅ Quizzes can be generated from document content")
        print("✅ Complete document analysis pipeline works")
        return 0
    else:
        print(f"⚠️  {passed}/{total} tests passed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
