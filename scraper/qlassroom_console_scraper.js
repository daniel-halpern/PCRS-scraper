// =========================================================================
// Qlassroom 1-Click Lecture Notes Scraper
// Instructions:
// 1. Open https://www.qlassroom.app/course/7 in Google Chrome / Safari / Edge
// 2. Open Developer Tools (Press F12 or Cmd + Option + I on Mac)
// 3. Click the "Console" tab
// 4. Paste this entire script and press Enter
//
// It will automatically pull all chapters, sections, and LaTeX notes,
// download both .md and .tex files, and copy the markdown to your clipboard!
// =========================================================================

(async function scrapeQlassroom() {
  console.log("%c🚀 Starting Qlassroom lecture notes extraction...", "color: #3b82f6; font-size: 14px; font-weight: bold;");

  // 1. Extract Supabase Auth Token from localStorage
  let token = null;
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key.includes("auth-token") || key.includes("supabase")) {
      try {
        const parsed = JSON.parse(localStorage.getItem(key));
        if (parsed.access_token) {
          token = parsed.access_token;
          break;
        } else if (parsed.currentSession?.access_token) {
          token = parsed.currentSession.access_token;
          break;
        }
      } catch (e) {}
    }
  }

  const SUPABASE_URL = "https://txrblvnqkuaspvpzlnku.supabase.co";
  const ANON_KEY = "sb_publishable_EqZGmIcDAY8qt4ZrZhN3qA_BNbF94gy";
  const authHeader = token ? `Bearer ${token}` : `Bearer ${ANON_KEY}`;

  console.log(token ? "%c🔑 Authenticated session found!" : "%c⚠️ No session token found, trying anon key...", "color: #10b981; font-weight: bold;");

  const headers = {
    "apikey": ANON_KEY,
    "Authorization": authHeader,
    "Content-Type": "application/json"
  };

  // Determine Course ID from URL
  const courseMatch = window.location.pathname.match(/\/course\/(\d+)/) || window.location.search.match(/courseId=(\d+)/);
  const courseId = courseMatch ? parseInt(courseMatch[1], 10) : 7;

  console.log(`📡 Fetching metadata for Course ID ${courseId}...`);

  // Fetch course metadata
  const courseRes = await fetch(`${SUPABASE_URL}/rest/v1/courses?id=eq.${courseId}`, { headers });
  const [course] = await courseRes.json();
  const courseTitle = course?.title || `Course_${courseId}`;

  // Fetch chapters
  const chapRes = await fetch(`${SUPABASE_URL}/rest/v1/chapters?course_id=eq.${courseId}&order=order_num.asc`, { headers });
  const chapters = await chapRes.json();

  // Fetch all lessons
  const lessonRes = await fetch(`${SUPABASE_URL}/rest/v1/lessons?order=order_num.asc`, { headers });
  const allLessons = await lessonRes.json();

  // Fetch course preamble if available
  let preamble = "";
  try {
    const preRes = await fetch(`${SUPABASE_URL}/rest/v1/course_latex_settings?course_id=eq.${courseId}`, { headers });
    const preData = await preRes.json();
    if (preData?.[0]?.preamble) preamble = preData[0].preamble;
  } catch (e) {}

  let fullMarkdown = `# ${courseTitle}\n\n*Exported from Qlassroom on ${new Date().toLocaleDateString()}*\n\n---\n\n`;
  let fullLatex = `% ${courseTitle} - Compiled Lecture Notes\n`;
  if (preamble) fullLatex += `% Course Preamble:\n${preamble}\n\n`;

  let notesCount = 0;

  for (const ch of chapters) {
    const chTitle = `Chapter ${ch.order_num}: ${ch.title}`;
    console.log(`%c📖 ${chTitle}`, "color: #2563eb; font-weight: bold;");
    fullMarkdown += `# ${chTitle}\n\n`;
    if (ch.description) fullMarkdown += `> ${ch.description}\n\n`;

    fullLatex += `\n\\chapter{${ch.title}}\n\n`;
    if (ch.description) fullLatex += `% ${ch.description}\n\n`;

    const chLessons = allLessons
      .filter(l => l.chapter_id === ch.id)
      .sort((a, b) => a.order_num - b.order_num);

    for (const l of chLessons) {
      const lTitle = `Section ${ch.order_num}.${l.order_num}: ${l.title}`;
      console.log(`   📝 ${lTitle}`);
      fullMarkdown += `## ${lTitle}\n\n`;
      fullLatex += `\\section{${l.title}}\n\n`;

      let notes = "";

      // 1. Try RPC get_published_lecture_notes
      try {
        const rpcRes = await fetch(`${SUPABASE_URL}/rest/v1/rpc/get_published_lecture_notes`, {
          method: "POST",
          headers,
          body: JSON.stringify({ p_lesson_id: l.id })
        });
        const rpcData = await rpcRes.json();
        if (rpcData && rpcData.length > 0) {
          notes = rpcData[0].source_latex || "";
        }
      } catch (e) {
        console.warn(`Could not get notes via RPC for ${l.title}:`, e);
      }

      // 2. Fallback: Query lesson_lecture_notes table directly
      if (!notes) {
        try {
          const tblRes = await fetch(`${SUPABASE_URL}/rest/v1/lesson_lecture_notes?lesson_id=eq.${l.id}`, { headers });
          const tblData = await tblRes.json();
          if (tblData && tblData.length > 0) {
            notes = tblData[0].source_latex || tblData[0].draft_latex || "";
          }
        } catch (e) {}
      }

      if (notes.trim()) {
        notesCount++;
        fullMarkdown += `${notes.trim()}\n\n`;
        fullLatex += `${notes.trim()}\n\n`;
      } else {
        fullMarkdown += `*(No text content available or video lecture)*\n\n`;
        fullLatex += `% (No text content available)\n\n`;
      }
      fullMarkdown += `---\n\n`;
    }
  }

  function downloadFile(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  const safeTitle = courseTitle.replace(/[^a-zA-Z0-9_-]/g, "_");
  downloadFile(`${safeTitle}_Notes.md`, fullMarkdown, "text/markdown");
  downloadFile(`${safeTitle}_Notes.tex`, fullLatex, "text/x-tex");

  try {
    await navigator.clipboard.writeText(fullMarkdown);
    console.log("%c📋 Full markdown copied to clipboard!", "color: #10b981; font-weight: bold;");
  } catch (e) {}

  console.log(`%c🎉 Done! Extracted notes for ${notesCount} sections.`, "color: #10b981; font-size: 14px; font-weight: bold;");
  if (token) {
    console.log("%cYour Session Token (if you need it for the python scraper):", "color: #8b5cf6;");
    console.log(token);
  }
})();
