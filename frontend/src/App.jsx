import { useEffect, useMemo, useState } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8013";
const TOKEN_KEY = "aa_google_id_token";

async function parseResponse(response) {
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const detail = data?.detail || data?.message || "Request failed";
    throw new Error(detail);
  }

  return data;
}

function priorityClass(value) {
  const v = String(value || "").toLowerCase();
  if (v.includes("high")) return "priority-high";
  if (v.includes("medium")) return "priority-medium";
  return "priority-low";
}

function shuffleArray(items) {
  const next = [...items];
  for (let i = next.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [next[i], next[j]] = [next[j], next[i]];
  }
  return next;
}

function normalizeQuizQuestion(question, fallbackNumber) {
  const baseOptions = question?.options && typeof question.options === "object" ? question.options : {};
  const values = Object.values(baseOptions).filter((value) => value !== undefined && value !== null);
  while (values.length < 4) {
    values.push(`Option ${values.length + 1}`);
  }

  const letters = ["A", "B", "C", "D"];
  const normalizedOptions = {};
  letters.forEach((letter, idx) => {
    normalizedOptions[letter] = String(values[idx] ?? `Option ${idx + 1}`);
  });

  const desiredCorrect = String(question?.correct_answer || "A").toUpperCase();
  const correctAnswer = letters.includes(desiredCorrect) ? desiredCorrect : "A";

  return {
    question_number: Number(question?.question_number || fallbackNumber),
    topic: question?.topic || "Document concepts",
    difficulty: question?.difficulty || "medium",
    question: question?.question || "Question unavailable",
    options: normalizedOptions,
    correct_answer: correctAnswer,
    explanation: question?.explanation || "Based on the uploaded document.",
  };
}

function shuffleQuizQuestion(question, fallbackNumber) {
  const normalized = normalizeQuizQuestion(question, fallbackNumber);
  const entries = shuffleArray(Object.entries(normalized.options));
  const letters = ["A", "B", "C", "D"];
  const shuffledOptions = {};

  entries.forEach(([letter, value], idx) => {
    shuffledOptions[letters[idx]] = value;
  });

  const correctValue = normalized.options[normalized.correct_answer];
  const newCorrect = letters.find((letter, idx) => shuffledOptions[letter] === correctValue) || "A";

  return {
    ...normalized,
    options: shuffledOptions,
    correct_answer: newCorrect,
  };
}

function prepareQuizQuestions(questions) {
  return shuffleArray((questions || []).map((question, index) => shuffleQuizQuestion(question, index + 1)));
}

function App() {
  const [auth, setAuth] = useState({
    loading: true,
    token: "",
    user: null,
    sessionId: "",
  });
  const [pendingAuthUrl, setPendingAuthUrl] = useState("");

  const [uploadedDocs, setUploadedDocs] = useState([]);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [activeView, setActiveView] = useState({ type: "main", docId: null });

  const [prereqData, setPrereqData] = useState({});
  const [quizData, setQuizData] = useState({});
  const [quizQuestionCount, setQuizQuestionCount] = useState({});

  const [chatHistory, setChatHistory] = useState([]);
  const [geminiHistory, setGeminiHistory] = useState([]);
  const [agentState, setAgentState] = useState({});
  const [chatInput, setChatInput] = useState("");

  const [planId, setPlanId] = useState(null);
  const [currentPlan, setCurrentPlan] = useState(null);

  const [requestText, setRequestText] = useState("Plan my study schedule for this week.");
  const [dailyHours, setDailyHours] = useState(2);
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [startTime, setStartTime] = useState("09:00");
  const [weakSubjectsText, setWeakSubjectsText] = useState("");

  const [feedbackMsg, setFeedbackMsg] = useState("Too much workload");
  const [feedbackDate, setFeedbackDate] = useState(new Date().toISOString().slice(0, 10));
  const [useAllDocsForPlan, setUseAllDocsForPlan] = useState(true);
  const [selectedPlanDocIds, setSelectedPlanDocIds] = useState([]);
  const [planSelectedDocs, setPlanSelectedDocs] = useState([]);

  const [notice, setNotice] = useState({ type: "info", text: "Ready." });
  const [busy, setBusy] = useState({
    docs: false,
    plan: false,
    feedback: false,
    chat: false,
    prereq: false,
    quiz: false,
  });

  const activeDoc = useMemo(
    () => uploadedDocs.find((d) => d.id === activeView.docId) || null,
    [uploadedDocs, activeView.docId]
  );

  useEffect(() => {
    void bootstrapAuth();
  }, []);

  useEffect(() => {
    setSelectedPlanDocIds((prev) => prev.filter((id) => uploadedDocs.some((doc) => doc.id === id)));
  }, [uploadedDocs]);

  useEffect(() => {
    if (useAllDocsForPlan) {
      return;
    }
    if (uploadedDocs.length > 0 && selectedPlanDocIds.length === 0) {
      setSelectedPlanDocIds(uploadedDocs.map((doc) => doc.id));
    }
  }, [useAllDocsForPlan, uploadedDocs, selectedPlanDocIds.length]);

  async function authFetch(path, options = {}) {
    if (!auth.token) {
      throw new Error("Please sign in with Google first.");
    }

    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${auth.token}`);

    return fetch(`${API}${path}`, {
      ...options,
      headers,
    });
  }

  async function bootstrapAuth() {
    try {
      const cfgRes = await fetch(`${API}/auth/config`);
      const cfg = await parseResponse(cfgRes);
      void cfg;

      const savedToken = localStorage.getItem(TOKEN_KEY);
      if (savedToken) {
        const meRes = await fetch(`${API}/auth/me`, {
          headers: { Authorization: `Bearer ${savedToken}` },
        });
        const me = await parseResponse(meRes);
        setAuth({
          loading: false,
          token: savedToken,
          user: me.user,
          sessionId: "",
        });
        setNotice({ type: "success", text: `Signed in as ${me.user.email || me.user.name}.` });
        await refreshDocuments(savedToken);
        return;
      }

      setAuth((prev) => ({ ...prev, loading: false }));
      setNotice({ type: "info", text: "Sign in to load your personal workspace." });
    } catch (err) {
      localStorage.removeItem(TOKEN_KEY);
      setAuth((prev) => ({ ...prev, loading: false }));
      setNotice({ type: "error", text: `Auth setup failed: ${err.message}` });
    }
  }

  async function verifyCredential(credential, saveToken = false) {
    try {
      const res = await fetch(`${API}/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential }),
      });
      const data = await parseResponse(res);

      if (saveToken) {
        localStorage.setItem(TOKEN_KEY, credential);
      }

      setAuth({
        loading: false,
        token: credential,
        user: data.user,
        sessionId: "",
      });

      setNotice({ type: "success", text: `Signed in as ${data.user.email || data.user.name}.` });
      await refreshDocuments(credential);
    } catch (err) {
      localStorage.removeItem(TOKEN_KEY);
      setAuth((prev) => ({ ...prev, loading: false, token: "", user: null }));
      setNotice({ type: "error", text: `Google sign-in failed: ${err.message}` });
    }
  }

  async function startGoogleSignIn() {
    setBusy((s) => ({ ...s, chat: true }));
    try {
      const res = await fetch(`${API}/auth/google/start`, {
        method: "POST",
      });
      const data = await parseResponse(res);
      setAuth((prev) => ({ ...prev, sessionId: data.session_id }));
      setPendingAuthUrl(data.auth_url || "");

      if (data.auth_url) {
        const popup = window.open(
          data.auth_url,
          "aa-google-signin",
          "popup=yes,width=520,height=680,noopener,noreferrer"
        );
        if (!popup) {
          setNotice({
            type: "warning",
            text: "Popup blocked. Click Open Sign-In Page below.",
          });
        } else {
          popup.focus();
          setNotice({ type: "info", text: "Google sign-in opened in a separate window. Complete it, then return here." });
        }
      } else {
        setNotice({ type: "error", text: "Sign-in URL missing from server response." });
      }
    } catch (err) {
      setNotice({ type: "error", text: `Could not start Google sign-in: ${err.message}` });
    } finally {
      setBusy((s) => ({ ...s, chat: false }));
    }
  }

  useEffect(() => {
    if (!auth.sessionId || auth.user) {
      return;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const res = await fetch(`${API}/auth/google/status/${auth.sessionId}`);
        const data = await parseResponse(res);

        if (cancelled) return;

        if (data.status === "complete" && data.session_token) {
          localStorage.setItem(TOKEN_KEY, data.session_token);
          setAuth({
            loading: false,
            token: data.session_token,
            user: data.user,
            sessionId: "",
          });
          setPendingAuthUrl("");
          setNotice({ type: "success", text: `Signed in as ${data.user.email || data.user.name}.` });
          await refreshDocuments(data.session_token);
          return;
        }

        if (data.status === "error") {
          setPendingAuthUrl("");
          setNotice({ type: "error", text: `Google sign-in failed: ${data.error || "unknown error"}` });
          setAuth((prev) => ({ ...prev, sessionId: "" }));
          return;
        }

        setTimeout(poll, 1500);
      } catch (err) {
        if (!cancelled) {
          setPendingAuthUrl("");
          setNotice({ type: "error", text: `Sign-in polling failed: ${err.message}` });
          setAuth((prev) => ({ ...prev, sessionId: "" }));
        }
      }
    };

    void poll();

    return () => {
      cancelled = true;
    };
  }, [auth.sessionId, auth.user]);

  function signOut() {
    localStorage.removeItem(TOKEN_KEY);
    setPendingAuthUrl("");
    setAuth((prev) => ({ ...prev, token: "", user: null, sessionId: "" }));
    setUploadedDocs([]);
    setPrereqData({});
    setQuizData({});
    setActiveView({ type: "main", docId: null });
    setNotice({ type: "info", text: "Signed out." });
  }

  async function refreshDocuments(explicitToken = "") {
    try {
      const token = explicitToken || auth.token;
      if (!token) return;

      const res = await fetch(`${API}/documents`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await parseResponse(res);
      setUploadedDocs(data.documents || []);
    } catch (err) {
      setNotice({ type: "error", text: `Failed to load documents: ${err.message}` });
    }
  }

  async function ingestDocuments() {
    if (!pendingFiles.length) {
      setNotice({ type: "warning", text: "Select at least one PDF first." });
      return;
    }

    setBusy((s) => ({ ...s, docs: true }));
    const created = [];

    try {
      for (const file of pendingFiles) {
        const form = new FormData();
        form.append("file", file);

        const res = await authFetch(`/upload`, {
          method: "POST",
          body: form,
        });
        const data = await parseResponse(res);

        created.push({
          id: data.document_id,
          filename: data.filename,
          chunks: data.chunks,
        });
      }

      setPendingFiles([]);
      await refreshDocuments();

      const names = created.map((d) => d.filename).join(", ");
      setNotice({ type: "success", text: `Ingested ${created.length} document(s): ${names}` });
    } catch (err) {
      setNotice({ type: "error", text: `Document ingest failed: ${err.message}` });
    } finally {
      setBusy((s) => ({ ...s, docs: false }));
    }
  }

  async function loadPrerequisites(docId) {
    if (prereqData[docId]) {
      setActiveView({ type: "prereq", docId });
      return;
    }

    setBusy((s) => ({ ...s, prereq: true }));
    setNotice({ type: "info", text: "Analyzing prerequisites from full document..." });

    try {
      const res = await authFetch(`/prerequisites/${docId}`);
      const data = await parseResponse(res);
      setPrereqData((prev) => ({ ...prev, [docId]: data }));
      setActiveView({ type: "prereq", docId });
      setNotice({ type: "success", text: "Prerequisite analysis ready." });
    } catch (err) {
      setNotice({ type: "error", text: `Failed to load prerequisites: ${err.message}` });
    } finally {
      setBusy((s) => ({ ...s, prereq: false }));
    }
  }

  async function generateQuiz(docId) {
    const count = Number(quizQuestionCount[docId] || 10);
    setBusy((s) => ({ ...s, quiz: true }));
    setNotice({ type: "info", text: `Generating ${count} quiz questions...` });

    try {
      const res = await authFetch(`/quiz/${docId}?num_questions=${count}`);
      const data = await parseResponse(res);
      const sourceQuestions = (data.questions || []).map((question, index) => normalizeQuizQuestion(question, index + 1));
      const questions = prepareQuizQuestions(sourceQuestions);

      setQuizData((prev) => ({
        ...prev,
        [docId]: {
          sourceQuestions,
          questions,
          answers: {},
          submitted: false,
          score: 0,
        },
      }));

      setActiveView({ type: "quiz", docId });
      setNotice({ type: "success", text: "Quiz generated successfully." });
    } catch (err) {
      setNotice({ type: "error", text: `Failed to generate quiz: ${err.message}` });
    } finally {
      setBusy((s) => ({ ...s, quiz: false }));
    }
  }

  async function createPlan() {
    setBusy((s) => ({ ...s, plan: true }));
    setNotice({ type: "info", text: "Building your study plan..." });

    try {
      if (!useAllDocsForPlan && selectedPlanDocIds.length === 0) {
        throw new Error("Select at least one document for planning, or choose All Documents.");
      }

      const payload = {
        request: requestText,
        daily_hours: Number(dailyHours),
        weak_subjects: weakSubjectsText
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        start_date: startDate,
        start_time: startTime,
        document_ids: selectedPlanDocIds,
        use_all_documents: useAllDocsForPlan,
      };

      const res = await authFetch(`/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await parseResponse(res);
      setPlanId(data.plan_id);
      setCurrentPlan(data.plan);
      setPlanSelectedDocs(data.selected_documents || []);
      setAgentState((prev) => ({ ...prev, plan_id: data.plan_id, current_plan: data.plan }));

      setNotice({
        type: "success",
        text: `Plan created successfully. ${data.calendar_events || 0} calendar event(s) scheduled.`,
      });
    } catch (err) {
      setNotice({ type: "error", text: `Plan generation failed: ${err.message}` });
    } finally {
      setBusy((s) => ({ ...s, plan: false }));
    }
  }

  async function updatePlanFromFeedback() {
    if (!planId) {
      setNotice({ type: "warning", text: "Create a plan first before updating it." });
      return;
    }

    setBusy((s) => ({ ...s, feedback: true }));
    setNotice({ type: "info", text: "Re-planning based on your feedback..." });

    try {
      const res = await authFetch(`/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_id: planId,
          feedback: feedbackMsg,
          start_date: feedbackDate,
          start_time: startTime,
        }),
      });

      const data = await parseResponse(res);
      setCurrentPlan(data.updated_plan);
      setAgentState((prev) => ({ ...prev, current_plan: data.updated_plan }));

      setNotice({ type: "success", text: "Plan updated successfully." });
    } catch (err) {
      setNotice({ type: "error", text: `Update failed: ${err.message}` });
    } finally {
      setBusy((s) => ({ ...s, feedback: false }));
    }
  }

  async function sendChat() {
    const text = chatInput.trim();
    if (!text || busy.chat) return;

    const nextChat = [...chatHistory, { role: "user", content: text }];
    setChatHistory(nextChat);
    setChatInput("");
    setBusy((s) => ({ ...s, chat: true }));

    try {
      const res = await authFetch(`/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: geminiHistory,
          session_state: {
            ...agentState,
            ...(planId ? { plan_id: planId } : {}),
            ...(currentPlan ? { current_plan: currentPlan } : {}),
            start_date: startDate,
            start_time: startTime,
          },
          plan_id: planId,
          current_plan: currentPlan,
          start_date: startDate,
          start_time: startTime,
        }),
      });

      const data = await parseResponse(res);
      setGeminiHistory(data.history || []);
      setAgentState(data.session_state || {});
      if (data.updated_plan) {
        setCurrentPlan(data.updated_plan);
      }
      if (data.session_state?.plan_id) {
        setPlanId(data.session_state.plan_id);
      }

      setChatHistory((prev) => [...prev, { role: "assistant", content: data.reply }]);
    } catch (err) {
      setChatHistory((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${err.message}` },
      ]);
    } finally {
      setBusy((s) => ({ ...s, chat: false }));
    }
  }

  function updateAnswer(docId, questionNumber, letter) {
    setQuizData((prev) => {
      const old = prev[docId];
      if (!old) return prev;
      return {
        ...prev,
        [docId]: {
          ...old,
          answers: {
            ...old.answers,
            [String(questionNumber)]: letter,
          },
        },
      };
    });
  }

  function submitQuiz(docId) {
    setQuizData((prev) => {
      const quiz = prev[docId];
      if (!quiz) return prev;

      const score = quiz.questions.reduce((acc, q) => {
        const chosen = quiz.answers[String(q.question_number)];
        return acc + (chosen === q.correct_answer ? 1 : 0);
      }, 0);

      return {
        ...prev,
        [docId]: {
          ...quiz,
          submitted: true,
          score,
        },
      };
    });
  }

  function retakeQuiz(docId) {
    setQuizData((prev) => {
      const quiz = prev[docId];
      if (!quiz) return prev;
      const sourceQuestions = quiz.sourceQuestions || quiz.questions || [];
      return {
        ...prev,
        [docId]: {
          ...quiz,
          questions: prepareQuizQuestions(sourceQuestions),
          answers: {},
          submitted: false,
          score: 0,
        },
      };
    });
  }

  function renderMain() {
    return (
      <div className="layout">
        <section className="panel chat-panel">
          <div className="panel-title-row">
            <h2>Study Copilot</h2>
            <span className="pill">Ollama-first</span>
          </div>
          <p className="muted">
            Ask for scheduling, topic help, document Q&A, and plan changes in one conversation.
          </p>

          <div className="chat-box">
            {chatHistory.length === 0 && (
              <div className="chat-empty">No messages yet. Start with a question about your studies.</div>
            )}
            {chatHistory.map((msg, idx) => (
              <div key={idx} className={`bubble ${msg.role}`}>
                <div className="bubble-role">{msg.role === "user" ? "You" : "Assistant"}</div>
                <div>{msg.content}</div>
              </div>
            ))}
          </div>

          <div className="chat-input-row">
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void sendChat();
              }}
              placeholder="Ask anything about your study plan..."
            />
            <button className="btn primary" onClick={sendChat} disabled={busy.chat}>
              {busy.chat ? "Thinking..." : "Send"}
            </button>
          </div>

          {currentPlan && (
            <div className="timetable">
              <div className="panel-header-block">
                <div>
                  <h3>Current Timetable</h3>
                  <p className="muted">
                    <strong>{currentPlan.plan_name || "Study Plan"}</strong>
                    {currentPlan.strategy ? ` • ${currentPlan.strategy}` : ""}
                  </p>
                </div>
                {currentPlan.summary && <div className="summary-badge">{currentPlan.summary}</div>}
              </div>
              {!!planSelectedDocs.length && (
                <div className="plan-selected-docs">
                  <span className="muted">Built from:</span>
                  <div className="plan-selected-docs-list">
                    {planSelectedDocs.map((doc) => (
                      <span className="plan-selected-doc" key={doc.id || doc.filename}>
                        {doc.filename}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div className="days-grid">
                {(currentPlan.days || []).map((dayBlock, idx) => (
                  <div className="day-card" key={idx}>
                    <h4>
                      {dayBlock.day}
                      {dayBlock.day_date ? ` • ${dayBlock.day_date}` : ""}
                    </h4>
                    {dayBlock.study_goal && <div className="day-goal">{dayBlock.study_goal}</div>}
                    {(dayBlock.tasks || []).map((task, tIdx) => (
                      <div className="task-card" key={tIdx}>
                        <div className="task-top-row">
                          <div className="task-time">{task.timeframe || "--:--"}</div>
                          <div className={`task-priority ${priorityClass(task.priority)}`}>{task.priority}</div>
                        </div>
                        <div className="task-topic">{task.topic}</div>
                        {task.what_to_cover && <div className="task-detail"><strong>What:</strong> {task.what_to_cover}</div>}
                        {task.how_to_study && <div className="task-detail"><strong>How:</strong> {task.how_to_study}</div>}
                        {task.why_now && <div className="task-detail"><strong>Why now:</strong> {task.why_now}</div>}
                        {task.source_document && <div className="task-detail muted">Source: {task.source_document}</div>}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        <aside className="side-column">
          <section className="panel">
            <h2>Documents</h2>
            <p className="muted">Upload PDFs, then run prerequisite analysis or generate a quiz.</p>

            <input
              type="file"
              accept="application/pdf"
              multiple
              onChange={(e) => setPendingFiles(Array.from(e.target.files || []))}
            />
            <button className="btn primary full" onClick={ingestDocuments} disabled={busy.docs}>
              {busy.docs ? "Ingesting..." : "Ingest Documents"}
            </button>

            <div className="doc-list">
              {uploadedDocs.length === 0 && <div className="muted">No uploaded documents yet.</div>}
              {uploadedDocs.map((doc) => (
                <div className="doc-card" key={doc.id}>
                  <div>
                    <div className="doc-name">{doc.filename}</div>
                    <div className="muted">{doc.num_chunks} chunks</div>
                  </div>
                  <div className="doc-actions">
                    <button className="btn ghost" onClick={() => void loadPrerequisites(doc.id)}>
                      Prerequisites
                    </button>
                    <button className="btn ghost" onClick={() => setActiveView({ type: "quiz", docId: doc.id })}>
                      Quiz
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel">
            <h2>Quick Plan</h2>
            <label>What do you need?</label>
            <textarea value={requestText} onChange={(e) => setRequestText(e.target.value)} rows={3} />

            <div className="grid-2">
              <div>
                <label>Daily hours</label>
                <input
                  type="number"
                  min={1}
                  max={8}
                  step={0.5}
                  value={dailyHours}
                  onChange={(e) => setDailyHours(e.target.value)}
                />
              </div>
              <div>
                <label>Start time</label>
                <input value={startTime} onChange={(e) => setStartTime(e.target.value)} />
              </div>
            </div>

            <div className="grid-2">
              <div>
                <label>Start date</label>
                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
              </div>
              <div>
                <label>Weak subjects</label>
                <input
                  value={weakSubjectsText}
                  onChange={(e) => setWeakSubjectsText(e.target.value)}
                  placeholder="Math, Physics"
                />
              </div>
            </div>

            <button className="btn primary full" onClick={createPlan} disabled={busy.plan}>
              {busy.plan ? "Generating..." : "Generate Plan"}
            </button>

            <div className="plan-doc-picker">
              <label className="plan-toggle">
                <input
                  type="checkbox"
                  checked={useAllDocsForPlan}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setUseAllDocsForPlan(checked);
                    if (checked) {
                      setSelectedPlanDocIds([]);
                    }
                  }}
                />
                <span>Use all uploaded documents for this plan</span>
              </label>

              {!useAllDocsForPlan && (
                <div className="plan-doc-chooser">
                  <div className="muted plan-doc-chooser-title">
                    Choose one or more documents:
                  </div>
                  {uploadedDocs.length === 0 && <div className="muted">No documents uploaded yet.</div>}
                  {uploadedDocs.map((doc) => {
                    const checked = selectedPlanDocIds.includes(doc.id);
                    return (
                      <label key={doc.id} className="plan-doc-option">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const on = e.target.checked;
                            setSelectedPlanDocIds((prev) => {
                              if (on) return [...new Set([...prev, doc.id])];
                              return prev.filter((id) => id !== doc.id);
                            });
                          }}
                        />
                        <span>{doc.filename}</span>
                      </label>
                    );
                  })}
                  {!!uploadedDocs.length && (
                    <div className="button-row plan-doc-actions">
                      <button className="btn ghost" onClick={() => setSelectedPlanDocIds(uploadedDocs.map((d) => d.id))}>
                        Select All
                      </button>
                      <button className="btn ghost" onClick={() => setSelectedPlanDocIds([])}>
                        Clear
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>

          <section className="panel">
            <h2>Feedback</h2>
            <label>How is your current plan going?</label>
            <input value={feedbackMsg} onChange={(e) => setFeedbackMsg(e.target.value)} />

            <label>Reschedule from</label>
            <input type="date" value={feedbackDate} onChange={(e) => setFeedbackDate(e.target.value)} />

            <button className="btn full" onClick={updatePlanFromFeedback} disabled={busy.feedback}>
              {busy.feedback ? "Updating..." : "Update Plan"}
            </button>
          </section>
        </aside>
      </div>
    );
  }

  function renderPrereq() {
    const data = prereqData[activeView.docId];
    const analysis = data?.analysis || {};
    const prereqs = analysis.prerequisites || [];

    const must = prereqs.filter((p) => p.urgency === "must_know");
    const good = prereqs.filter((p) => p.urgency === "good_to_know");
    const optional = prereqs.filter((p) => p.urgency === "optional");

    return (
      <div className="single-view">
        <button className="btn ghost" onClick={() => setActiveView({ type: "main", docId: null })}>
          Back
        </button>

        <div className="panel">
          <div className="panel-header-block">
            <div>
              <h2>Prerequisites: {activeDoc?.filename || "Document"}</h2>
              <p className="muted">Built from the selected document and the content extracted from it.</p>
            </div>
            <div className="summary-badge">
              {prereqs.length} prerequisite{prereqs.length === 1 ? "" : "s"} • {analysis.topics_covered?.length || 0} topics
            </div>
          </div>
          <div className="metric-row">
            <div className="metric"><span>Subject</span><strong>{analysis.subject || "-"}</strong></div>
            <div className="metric"><span>Type</span><strong>{analysis.document_type || "-"}</strong></div>
            <div className="metric"><span>Difficulty</span><strong>{analysis.difficulty_level || "-"}</strong></div>
            <div className="metric"><span>Total Hours</span><strong>{analysis.total_estimated_hours || 0}h</strong></div>
          </div>

          {analysis.summary && <div className="summary-box">{analysis.summary}</div>}

          <div className="three-col">
            <div>
              <h3>Must Know</h3>
              {must.length === 0 && <p className="muted">None</p>}
              {must.map((p, idx) => (
                <div className="req-card red" key={idx}>
                  <strong>{p.topic}</strong>
                  <p>{p.reason}</p>
                  {p.resources && <small>{p.resources}</small>}
                </div>
              ))}
            </div>
            <div>
              <h3>Good to Know</h3>
              {good.length === 0 && <p className="muted">None</p>}
              {good.map((p, idx) => (
                <div className="req-card amber" key={idx}>
                  <strong>{p.topic}</strong>
                  <p>{p.reason}</p>
                  {p.resources && <small>{p.resources}</small>}
                </div>
              ))}
            </div>
            <div>
              <h3>Optional</h3>
              {optional.length === 0 && <p className="muted">None</p>}
              {optional.map((p, idx) => (
                <div className="req-card green" key={idx}>
                  <strong>{p.topic}</strong>
                  <p>{p.reason}</p>
                  {p.resources && <small>{p.resources}</small>}
                </div>
              ))}
            </div>
          </div>

          {(analysis.topics_covered || []).length > 0 && (
            <>
              <h3>Topics Covered</h3>
              <div className="topic-list">
                {analysis.topics_covered.map((t, idx) => (
                  <div className="topic-pill" key={idx}>
                    <span className="topic-pill-name">{t.topic}</span>
                    <span className="topic-pill-meta">{t.difficulty} • ~{t.estimated_hours}h</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {(analysis.suggested_study_order || []).length > 0 && (
            <>
              <h3>Suggested Study Order</h3>
              <ol className="order-list">
                {analysis.suggested_study_order.map((topic, idx) => (
                  <li key={idx}>{topic}</li>
                ))}
              </ol>
            </>
          )}

          <button className="btn primary" onClick={() => setActiveView({ type: "quiz", docId: activeView.docId })}>
            Take Quiz on This Document
          </button>
        </div>
      </div>
    );
  }

  function renderQuiz() {
    const docId = activeView.docId;
    const quiz = quizData[docId];

    if (!quiz) {
      const count = Number(quizQuestionCount[docId] || 10);

      return (
        <div className="single-view">
          <button className="btn ghost" onClick={() => setActiveView({ type: "main", docId: null })}>
            Back
          </button>

          <div className="panel">
            <h2>Quiz: {activeDoc?.filename || "Document"}</h2>
            <div className="grid-2">
              <div>
                <label>Number of questions</label>
                <select
                  value={count}
                  onChange={(e) =>
                    setQuizQuestionCount((prev) => ({ ...prev, [docId]: Number(e.target.value) }))
                  }
                >
                  {[5, 10, 15, 20].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <button className="btn primary" onClick={() => void generateQuiz(docId)} disabled={busy.quiz}>
              {busy.quiz ? "Generating..." : "Generate Quiz"}
            </button>
          </div>
        </div>
      );
    }

    const total = quiz.questions.length;
    const answered = Object.keys(quiz.answers).length;
    const unanswered = Math.max(0, total - answered);

    if (quiz.submitted) {
      const pct = total ? Math.round((quiz.score / total) * 100) : 0;

      return (
        <div className="single-view">
          <button className="btn ghost" onClick={() => setActiveView({ type: "main", docId: null })}>
            Back
          </button>

          <div className="panel">
            <h2>Quiz Results: {activeDoc?.filename || "Document"}</h2>
            <div className="score-banner">
              <strong>
                Score: {quiz.score}/{total} ({pct}%)
              </strong>
            </div>

            {quiz.questions.map((q) => {
              const chosen = quiz.answers[String(q.question_number)];
              const correct = q.correct_answer;
              const ok = chosen === correct;

              return (
                <div className="question-card" key={q.question_number}>
                  <h4>
                    {ok ? "Correct" : "Incorrect"} • Q{q.question_number} • {q.topic} • {q.difficulty}
                  </h4>
                  <p>{q.question}</p>
                  <ul className="options-review">
                    {Object.entries(q.options).map(([k, val]) => {
                      const cls = k === correct ? "correct" : chosen === k ? "wrong" : "";
                      return (
                        <li key={k} className={cls}>
                          <span className="review-letter">{k}</span>
                          <span className="review-text">{val}</span>
                        </li>
                      );
                    })}
                  </ul>
                  <div className="muted">Explanation: {q.explanation}</div>
                </div>
              );
            })}

            <div className="button-row">
              <button className="btn" onClick={() => retakeQuiz(docId)}>
                Retake Quiz
              </button>
              <button className="btn primary" onClick={() => setActiveView({ type: "prereq", docId })}>
                View Prerequisites
              </button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="single-view">
        <button className="btn ghost" onClick={() => setActiveView({ type: "main", docId: null })}>
          Back
        </button>

        <div className="panel">
          <div className="panel-header-block">
            <div>
              <h2>Quiz: {activeDoc?.filename || "Document"}</h2>
              <div className="muted">Progress: {answered}/{total} answered</div>
            </div>
            <div className="summary-badge">Retakes reshuffle answer order automatically.</div>
          </div>

          {quiz.questions.map((q) => {
            const selected = quiz.answers[String(q.question_number)] || "";
            return (
              <div className="question-card" key={q.question_number}>
                <h4>
                  Q{q.question_number} • {q.topic} • {q.difficulty}
                </h4>
                <p>{q.question}</p>

                <div className="option-grid">
                  {Object.entries(q.options).map(([letter, text]) => (
                    <label key={letter} className={`option-chip ${selected === letter ? "selected" : ""}`}>
                      <input
                        type="radio"
                        name={`q-${q.question_number}`}
                        checked={selected === letter}
                        onChange={() => updateAnswer(docId, q.question_number, letter)}
                      />
                      <span className="option-letter">{letter}</span>
                      <span className="option-text">{text}</span>
                    </label>
                  ))}
                </div>
              </div>
            );
          })}

          {unanswered > 0 && <div className="warn">You have {unanswered} unanswered question(s).</div>}

          <button className="btn primary" onClick={() => submitQuiz(docId)}>
            {unanswered === 0 ? "Submit Quiz" : `Submit Anyway (${unanswered} unanswered)`}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <h1>AI Academic Assistant</h1>
          <p>React-powered workspace for document intelligence, adaptive planning, and guided learning.</p>
        </div>
        <div className="hero-right">
          <div className={`status ${notice.type}`}>{notice.text}</div>
          {auth.user && (
            <div className="user-chip">
              {auth.user.picture && <img src={auth.user.picture} alt="User avatar" />}
              <div>
                <strong>{auth.user.name || "Signed in"}</strong>
                <small>{auth.user.email}</small>
              </div>
              <button className="btn ghost" onClick={signOut}>Sign out</button>
            </div>
          )}
        </div>
      </header>

      {!auth.user && (
        <div className="signin-wrap">
          <section className="panel signin-panel">
            <h2>Sign in with Google</h2>
            <p className="muted">
              Sign in to open your personal workspace and keep your uploaded documents under your account.
            </p>
            {auth.loading ? (
              <p className="muted">Preparing sign-in...</p>
            ) : (
              <>
                <button className="btn primary" onClick={startGoogleSignIn} disabled={busy.chat}>
                  {busy.chat ? "Opening Google sign-in..." : "Continue with Google"}
                </button>
                {!!pendingAuthUrl && (
                  <button
                    className="btn ghost"
                    style={{ marginTop: "10px" }}
                    onClick={() => window.open(pendingAuthUrl, "aa-google-signin", "popup=yes,width=520,height=680,noopener,noreferrer")}
                  >
                    Open Sign-In Page
                  </button>
                )}
              </>
            )}
          </section>
        </div>
      )}

      {auth.user && activeView.type === "main" && renderMain()}
      {auth.user && activeView.type === "prereq" && renderPrereq()}
      {auth.user && activeView.type === "quiz" && renderQuiz()}
    </div>
  );
}

export default App;
