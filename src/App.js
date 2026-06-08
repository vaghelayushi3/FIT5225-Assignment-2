import { useAuth } from "react-oidc-context";
import { useState } from "react";
import SparkMD5 from "spark-md5";

const API = "https://qmkxy2brdl.execute-api.us-east-1.amazonaws.com/prod";
const BUCKET = "aussie-ecolens-media-3125";

const calculateMD5 = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const md5 = SparkMD5.ArrayBuffer.hash(e.target.result);
      resolve(md5);
    };
    reader.onerror = reject;
    reader.readAsArrayBuffer(file);
  });
};

function App() {
  const auth = useAuth();
  const [file, setFile] = useState(null);
  const [uploadMsg, setUploadMsg] = useState("");
  const [queryTags, setQueryTags] = useState("");
  const [queryResults, setQueryResults] = useState([]);
  const [fullImage, setFullImage] = useState("");
  const [editUrls, setEditUrls] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editOp, setEditOp] = useState(1);
  const [deleteUrls, setDeleteUrls] = useState("");
  const [activeTab, setActiveTab] = useState("upload");
  const [queryFile, setQueryFile] = useState(null);
  const [queryFileResults, setQueryFileResults] = useState([]);
  const [queryFileMsg, setQueryFileMsg] = useState("");

  const signOutRedirect = () => {
    const clientId = "4pbcgreall8s87rhp4qj0al4pj";
    const logoutUri = "http://localhost:3000";
    const cognitoDomain = "https://us-east-1chmfus9qu.auth.us-east-1.amazoncognito.com";
    window.location.href = `${cognitoDomain}/logout?client_id=${clientId}&logout_uri=${encodeURIComponent(logoutUri)}`;
  };

  const getToken = () => {
    return auth.user?.id_token || auth.user?.access_token || "";
  };

  const callAPI = async (body) => {
    const res = await fetch(`${API}/query/tags`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": getToken()
      },
      body: JSON.stringify(body)
    });
    const outer = await res.json();
    return typeof outer.body === "string" ? JSON.parse(outer.body) : outer;
  };

  // ─── SINGLE uploadFile definition (inside App, uses MD5 checksum) ───────────
  const uploadFile = async () => {
    if (!file) {
      setUploadMsg("⚠️ Please select a file first.");
      return;
    }

    try {
      // Step 1: compute MD5 checksum
      setUploadMsg("🔍 Checking for duplicates...");
      const checksum = await calculateMD5(file);

      // Step 2: pre-check by checksum BEFORE uploading
      const preCheck = await callAPI({
        query_type: "check_upload",
        checksum: checksum
      });

      if (preCheck.exists) {
        setUploadMsg("⚠️ Duplicate file detected! This file already exists in the system.");
        return;
      }

      // Step 3: get presigned URL
      setUploadMsg("⏫ Uploading...");
      const timestamp = Date.now();
      const uniqueFilename = `${timestamp}_${file.name}`;

      const res = await fetch(`${API}/uploads`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": getToken()
        },
        body: JSON.stringify({ filename: uniqueFilename, filetype: file.type })
      });

      const outer = await res.json();
      const data = typeof outer.body === "string" ? JSON.parse(outer.body) : outer;

      if (!data.url) {
        setUploadMsg("❌ Failed to get upload URL.");
        return;
      }

      // Step 4: upload to S3 via presigned URL
      const uploadRes = await fetch(data.url, {
        method: "PUT",
        body: file,
        headers: { "Content-Type": file.type }
      });

      if (!uploadRes.ok) {
        setUploadMsg(`❌ Upload failed (${uploadRes.status})`);
        return;
      }

      // Step 5: wait for Lambda to process (thumbnail + ML tagging)
      setUploadMsg("⏳ Upload successful. Processing image and detecting species...");
      await new Promise(resolve => setTimeout(resolve, 20000));

      // Step 6: confirm processing by checking checksum in DB
      const postCheck = await callAPI({
        query_type: "check_upload",
        checksum: checksum
      });

      if (postCheck.exists) {
        setUploadMsg("✅ File uploaded and species detected successfully!");
      } else {
        // Lambda may have detected it as a duplicate of an existing file (same content, different name)
        setUploadMsg("✅ File uploaded successfully! (Processing may still be in progress)");
      }

    } catch (err) {
      console.error(err);
      setUploadMsg("❌ Error: " + err.message);
    }
  };

  const queryByTags = async () => {
    if (!queryTags.trim()) { alert("Please enter tags to search!"); return; }
    const tags = {};
    queryTags.split(",").forEach(t => {
      const parts = t.trim().split(":");
      const name = parts[0].trim();
      const count = parseInt(parts[1]) || 1;
      if (name) tags[name] = count;
    });
    try {
      const data = await callAPI({ tags, query_type: "tags" });
      setQueryResults(data.results || []);
      setFullImage("");
      if ((data.results || []).length === 0) alert("No files found with those tags!");
    } catch (err) {
      alert("Query error: " + err.message);
    }
  };

  const getThumbnailFull = async (thumbUrl) => {
    try {
      const data = await callAPI({ thumbnail_url: thumbUrl, query_type: "thumbnail" });
      if (data.s3_url) {
        setFullImage(data.s3_url);
      } else {
        alert("Could not find full-size image for this thumbnail.");
      }
    } catch (err) {
      alert("Error: " + err.message);
    }
  };

  const editTagsHandler = async () => {
    const urls = editUrls.split("\n").map(u => u.trim()).filter(u => u);
    const tags = editTags.split(",").map(t => t.trim()).filter(t => t);
    if (!urls.length || !tags.length) { alert("Enter URLs and tags!"); return; }
    try {
      const data = await callAPI({ urls, tags, operation: parseInt(editOp), query_type: "edit" });
      alert(data.message || "Tags updated successfully!");
    } catch (err) {
      alert("Error: " + err.message);
    }
  };

  const deleteFiles = async () => {
    const urls = deleteUrls.split("\n").map(u => u.trim()).filter(u => u);
    if (!urls.length) { alert("Enter URLs to delete!"); return; }
    try {
      const data = await callAPI({ urls, query_type: "delete" });
      alert(data.message || "Files deleted successfully!");
      setDeleteUrls("");
    } catch (err) {
      alert("Error: " + err.message);
    }
  };

  const queryByFile = async () => {
    if (!queryFile) { setQueryFileMsg("⚠️ Please select a file first."); return; }
    setQueryFileMsg("🔍 Analysing file...");
    setQueryFileResults([]);
    try {
      const reader = new FileReader();
      reader.onload = async (e) => {
        const base64 = e.target.result.split(",")[1];
        const data = await callAPI({ file_base64: base64, query_type: "query_file" });
        const results = data.results || [];
        setQueryFileResults(results);
        setQueryFileMsg(
          results.length > 0
            ? `Found ${results.length} matching file${results.length !== 1 ? "s" : ""}`
            : "No matching files found."
        );
      };
      reader.onerror = () => setQueryFileMsg("❌ Failed to read file.");
      reader.readAsDataURL(queryFile);
    } catch (err) {
      setQueryFileMsg("❌ Error: " + err.message);
    }
  };

  // ─── Auth loading / error states ────────────────────────────────────────────
  if (auth.isLoading) return <div style={s.center}>Loading...</div>;
  if (auth.error) return <div style={s.center}>Error: {auth.error.message}</div>;

  if (!auth.isAuthenticated) {
    return (
      <div style={s.loginPage}>
        <div style={s.loginBox}>
          <h1 style={s.logo}>🦘 Aussie EcoLens</h1>
          <p style={s.tagline}>Wildlife Observation Platform</p>
          <button style={s.btnPrimary} onClick={() => auth.signinRedirect()}>Sign In</button>
        </div>
      </div>
    );
  }

  // ─── Main App ────────────────────────────────────────────────────────────────
  return (
    <div style={s.app}>
      <header style={s.header}>
        <h1 style={s.logo}>🦘 Aussie EcoLens</h1>
        <div style={s.headerRight}>
          <span style={s.email}>{auth.user?.profile?.email}</span>
          <button style={s.btnSmall} onClick={signOutRedirect}>Sign Out</button>
        </div>
      </header>

      <nav style={s.nav}>
        {["upload", "query", "findbyfile", "tags", "delete"].map(tab => (
          <button
            key={tab}
            style={activeTab === tab ? s.tabActive : s.tab}
            onClick={() => setActiveTab(tab)}
          >
            {tab === "findbyfile" ? "Find by File" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </nav>

      <main style={s.main}>

        {/* ── Upload ── */}
        {activeTab === "upload" && (
          <div style={s.card}>
            <h2>Upload Media</h2>
            <p style={s.hint}>Upload wildlife images or videos. Species will be auto-detected.</p>
            <input
              type="file"
              accept="image/*,video/*"
              onChange={e => { setFile(e.target.files[0]); setUploadMsg(""); }}
              style={s.input}
            />
            {file && <p style={s.hint}>Selected: {file.name} ({(file.size / 1024).toFixed(1)} KB)</p>}
            <button style={s.btnPrimary} onClick={uploadFile}>Upload</button>
            {uploadMsg && <p style={s.msg}>{uploadMsg}</p>}
          </div>
        )}

        {/* ── Query by Tags ── */}
        {activeTab === "query" && (
          <div style={s.card}>
            <h2>Query by Tags</h2>
            <p style={s.hint}>Format: <code>koala:2,wombat:1</code> (finds files with ≥2 koalas AND ≥1 wombat). Omit count for "at least 1".</p>
            <input
              style={s.input}
              placeholder="e.g. koala:1  or  koala:2,wombat:1"
              value={queryTags}
              onChange={e => setQueryTags(e.target.value)}
              onKeyDown={e => e.key === "Enter" && queryByTags()}
            />
            <button style={s.btnPrimary} onClick={queryByTags}>Search</button>
            <div style={s.grid}>
              {queryResults.map((url, i) => (
                <div key={i} style={s.thumbWrapper}>
                  <img
                    src={url}
                    alt={`result-${i}`}
                    style={s.thumb}
                    onClick={() => getThumbnailFull(url)}
                    title="Click for full-size image"
                  />
                </div>
              ))}
            </div>
            {fullImage && (
              <div style={{ marginTop: "1.5rem" }}>
                <h3>Full-Size Image:</h3>
                <img src={fullImage} alt="full-size" style={{ maxWidth: "100%", borderRadius: "8px" }} />
                <p style={s.hint}><a href={fullImage} target="_blank" rel="noreferrer">Open in new tab ↗</a></p>
              </div>
            )}
          </div>
        )}

        {/* ── Find by File ── */}
        {activeTab === "findbyfile" && (
          <div style={s.card}>
            <h2>Find by File</h2>
            <p style={s.hint}>Upload a file to find all matching files in the database based on detected species.</p>
            <input
              type="file"
              accept="image/*,video/*"
              onChange={e => { setQueryFile(e.target.files[0]); setQueryFileMsg(""); setQueryFileResults([]); }}
              style={s.input}
            />
            <button style={s.btnPrimary} onClick={queryByFile}>Find Matches</button>
            {queryFileMsg && <p style={s.msg}>{queryFileMsg}</p>}
            <div style={s.grid}>
              {queryFileResults.map((url, i) => (
                <div key={i} style={s.thumbWrapper}>
                  <img src={url} alt={`match-${i}`} style={s.thumb} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Edit Tags ── */}
        {activeTab === "tags" && (
          <div style={s.card}>
            <h2>Edit Tags</h2>
            <p style={s.hint}>Paste file S3 URLs (one per line), enter tags to add/remove, then select the operation.</p>
            <textarea
              style={s.textarea}
              placeholder="Enter file URLs (one per line)&#10;https://aussie-ecolens-media-3125.s3.amazonaws.com/uploads/..."
              value={editUrls}
              onChange={e => setEditUrls(e.target.value)}
            />
            <input
              style={s.input}
              placeholder="Tags (comma-separated): koala,wombat,echidna"
              value={editTags}
              onChange={e => setEditTags(e.target.value)}
            />
            <select
              style={s.input}
              value={editOp}
              onChange={e => setEditOp(parseInt(e.target.value))}
            >
              <option value={1}>Add tags</option>
              <option value={0}>Remove tags</option>
            </select>
            <button style={s.btnPrimary} onClick={editTagsHandler}>Update Tags</button>
          </div>
        )}

        {/* ── Delete Files ── */}
        {activeTab === "delete" && (
          <div style={s.card}>
            <h2>Delete Files</h2>
            <p style={s.hint}>Paste S3 file URLs to permanently delete (one per line). This also removes thumbnails and database entries.</p>
            <textarea
              style={s.textarea}
              placeholder="Enter file URLs to delete (one per line)&#10;https://aussie-ecolens-media-3125.s3.amazonaws.com/uploads/..."
              value={deleteUrls}
              onChange={e => setDeleteUrls(e.target.value)}
            />
            <button style={s.btnDanger} onClick={deleteFiles}>Delete Files</button>
          </div>
        )}

      </main>
    </div>
  );
}

const s = {
  app: { fontFamily: "Arial, sans-serif", minHeight: "100vh", background: "#f0f4f8" },
  header: { background: "#1a5f3f", color: "white", padding: "1rem 2rem", display: "flex", justifyContent: "space-between", alignItems: "center" },
  headerRight: { display: "flex", alignItems: "center", gap: "1rem" },
  logo: { margin: 0, fontSize: "1.5rem" },
  tagline: { color: "#aaa", marginTop: "0.5rem" },
  email: { fontSize: "0.9rem" },
  nav: { background: "#fff", padding: "0.5rem 2rem", display: "flex", gap: "0.5rem", borderBottom: "1px solid #ddd", flexWrap: "wrap" },
  tab: { padding: "0.5rem 1rem", border: "none", background: "none", cursor: "pointer", borderRadius: "4px", fontSize: "0.9rem" },
  tabActive: { padding: "0.5rem 1rem", border: "none", background: "#1a5f3f", color: "white", cursor: "pointer", borderRadius: "4px", fontSize: "0.9rem" },
  main: { padding: "2rem", maxWidth: "900px", margin: "0 auto" },
  card: { background: "white", borderRadius: "8px", padding: "2rem", boxShadow: "0 2px 8px rgba(0,0,0,0.1)" },
  input: { display: "block", width: "100%", padding: "0.75rem", marginBottom: "1rem", border: "1px solid #ddd", borderRadius: "4px", fontSize: "1rem", boxSizing: "border-box" },
  textarea: { display: "block", width: "100%", padding: "0.75rem", marginBottom: "1rem", border: "1px solid #ddd", borderRadius: "4px", fontSize: "1rem", minHeight: "100px", boxSizing: "border-box", resize: "vertical" },
  btnPrimary: { background: "#1a5f3f", color: "white", border: "none", padding: "0.75rem 2rem", borderRadius: "4px", cursor: "pointer", fontSize: "1rem", marginBottom: "1rem" },
  btnDanger: { background: "#dc3545", color: "white", border: "none", padding: "0.75rem 2rem", borderRadius: "4px", cursor: "pointer", fontSize: "1rem" },
  btnSmall: { background: "transparent", color: "white", border: "1px solid white", padding: "0.4rem 1rem", borderRadius: "4px", cursor: "pointer" },
  loginPage: { minHeight: "100vh", background: "#1a5f3f", display: "flex", alignItems: "center", justifyContent: "center" },
  loginBox: { background: "white", borderRadius: "12px", padding: "3rem", textAlign: "center", boxShadow: "0 4px 20px rgba(0,0,0,0.2)" },
  center: { display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" },
  msg: { marginTop: "1rem", padding: "0.75rem", background: "#f0f9f0", borderRadius: "4px", color: "#2d6a4f" },
  hint: { color: "#888", fontSize: "0.9rem", marginBottom: "1rem" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: "1rem", marginTop: "1rem" },
  thumbWrapper: { overflow: "hidden", borderRadius: "4px", background: "#f5f5f5" },
  thumb: { width: "100%", display: "block", cursor: "pointer", transition: "opacity 0.2s" },
};

export default App;