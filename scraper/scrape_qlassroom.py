#!/usr/bin/env python3
"""
Qlassroom Lecture Notes Scraper
Fetches all chapters, sections, and LaTeX lecture notes from Qlassroom (Supabase backend).
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error

SUPABASE_URL = "https://txrblvnqkuaspvpzlnku.supabase.co"
ANON_KEY = "sb_publishable_EqZGmIcDAY8qt4ZrZhN3qA_BNbF94gy"

def fetch_json(endpoint, headers, method="GET", data=None):
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers=headers,
        method=method
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def scrape_course(course_id=7, auth_token=None, output_dir="output"):
    os.makedirs(output_dir, exist_ok=True)

    token = auth_token or ANON_KEY
    headers = {
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print(f"[*] Fetching course metadata for Course {course_id}...")
    courses = fetch_json(f"courses?id=eq.{course_id}", headers)
    if not courses:
        print(f"[!] Course {course_id} not found!")
        return
    course = courses[0]
    course_title = course.get("title", f"Course_{course_id}")
    print(f"[+] Found course: {course_title}")

    # Preamble
    preamble = ""
    try:
        pre_data = fetch_json(f"course_latex_settings?course_id=eq.{course_id}", headers)
        if pre_data and pre_data[0].get("preamble"):
            preamble = pre_data[0]["preamble"]
    except Exception as e:
        print(f"[-] Could not load preamble: {e}")

    # Chapters
    print("[*] Fetching chapters...")
    chapters = fetch_json(f"chapters?course_id=eq.{course_id}&order=order_num.asc", headers)
    print(f"[+] Found {len(chapters)} chapters.")

    # Lessons
    print("[*] Fetching lessons...")
    all_lessons = fetch_json("lessons?order=order_num.asc", headers)

    md_lines = [f"# {course_title}\n\n", "---\n\n"]
    tex_lines = [f"% {course_title} - Lecture Notes\n"]
    if preamble:
        tex_lines.append(f"% Course Preamble:\n{preamble}\n\n")

    total_notes_found = 0

    for ch in chapters:
        ch_num = ch.get("order_num")
        ch_title = ch.get("title")
        ch_desc = ch.get("description", "")
        ch_id = ch.get("id")

        print(f"\n📖 Chapter {ch_num}: {ch_title}")
        md_lines.append(f"# Chapter {ch_num}: {ch_title}\n\n")
        if ch_desc:
            md_lines.append(f"> {ch_desc}\n\n")

        tex_lines.append(f"\\chapter{{{ch_title}}}\n\n")
        if ch_desc:
            tex_lines.append(f"% {ch_desc}\n\n")

        ch_lessons = [l for l in all_lessons if l.get("chapter_id") == ch_id]
        ch_lessons.sort(key=lambda x: x.get("order_num", 0))

        for l in ch_lessons:
            l_num = l.get("order_num")
            l_title = l.get("title")
            l_id = l.get("id")

            print(f"   📝 Section {ch_num}.{l_num}: {l_title}")
            md_lines.append(f"## Section {ch_num}.{l_num}: {l_title}\n\n")
            tex_lines.append(f"\\section{{{l_title}}}\n\n")

            # Try get_published_lecture_notes RPC
            notes = ""
            try:
                rpc_res = fetch_json("rpc/get_published_lecture_notes", headers, method="POST", data={"p_lesson_id": l_id})
                if rpc_res and len(rpc_res) > 0:
                    notes = rpc_res[0].get("source_latex", "")
            except Exception as e:
                pass

            # Fallback to direct table query
            if not notes:
                try:
                    tbl_res = fetch_json(f"lesson_lecture_notes?lesson_id=eq.{l_id}", headers)
                    if tbl_res and len(tbl_res) > 0:
                        notes = tbl_res[0].get("source_latex") or tbl_res[0].get("draft_latex", "")
                except Exception:
                    pass

            if notes.strip():
                total_notes_found += 1
                md_lines.append(f"{notes.strip()}\n\n")
                tex_lines.append(f"{notes.strip()}\n\n")
            else:
                md_lines.append("*(No text content available)*\n\n")
                tex_lines.append("% (No text content available)\n\n")

            md_lines.append("---\n\n")

    safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in course_title)
    md_file = os.path.join(output_dir, f"{safe_title}_Notes.md")
    tex_file = os.path.join(output_dir, f"{safe_title}_Notes.tex")

    with open(md_file, "w", encoding="utf-8") as f:
        f.writelines(md_lines)

    with open(tex_file, "w", encoding="utf-8") as f:
        f.writelines(tex_lines)

    print(f"\n[+] Finished scraping! Notes retrieved for {total_notes_found} sections.")
    print(f"[+] Saved Markdown to: {md_file}")
    print(f"[+] Saved LaTeX to: {tex_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape lecture notes from Qlassroom")
    parser.add_argument("--course-id", type=int, default=7, help="Course ID (default: 7)")
    parser.add_argument("--token", type=str, default=None, help="User Supabase JWT access token")
    parser.add_argument("--out", type=str, default="output", help="Output directory")
    args = parser.parse_args()

    scrape_course(course_id=args.course_id, auth_token=args.token, output_dir=args.out)
