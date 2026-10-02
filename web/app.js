(() => {
  const MAX_BYTES = 20 * 1024 * 1024;
  const TYPES = {
    pdf: "application/pdf",
    txt: "text/plain",
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
  };
  const MESSAGES = {
    paid: "Waiting for the printer...",
    queued: "Sent to the printer...",
    received: "Printing...",
    printed: "Done. Take your document.",
  };

  const params = new URLSearchParams(location.search);
  const printer = params.get("p");
  const token = params.get("t");
  const api = window.CLOUDPRINT_API.replace(/\/$/, "");

  const fileInput = document.getElementById("file");
  const drop = document.getElementById("drop");
  const label = document.getElementById("file-label");
  const sendBtn = document.getElementById("send");
  const statusEl = document.getElementById("status");
  document.getElementById("printer").textContent = printer || "unknown";

  let file = null;

  function show(text, kind = "") {
    statusEl.textContent = text;
    statusEl.className = "status " + kind;
  }

  function pick(chosen) {
    const ext = chosen.name.split(".").pop().toLowerCase();
    if (!TYPES[ext]) return show("This file type is not supported.", "error");
    if (chosen.size > MAX_BYTES) return show("File is larger than 20 MB.", "error");
    file = chosen;
    label.textContent = chosen.name;
    sendBtn.disabled = false;
    show("");
  }

  fileInput.addEventListener("change", () => fileInput.files[0] && pick(fileInput.files[0]));
  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && pick(e.dataTransfer.files[0]));

  async function poll(jobId) {
    for (let i = 0; i < 90; i++) {
      const res = await fetch(`${api}/orders/${jobId}`);
      if (res.ok) {
        const { state, detail } = await res.json();
        if (state === "failed") return show(`Printing failed: ${detail || "unknown error"}`, "error");
        show(MESSAGES[state] || state, state === "printed" ? "ok" : "");
        if (state === "printed") return;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    show("The printer is taking too long. Ask the staff for help.", "error");
  }

  sendBtn.addEventListener("click", async () => {
    sendBtn.disabled = true;
    try {
      show("Uploading...");
      const created = await fetch(`${api}/orders`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ printer_id: printer, filename: file.name, token }),
      });
      if (!created.ok) {
        const msg = created.status === 403 ? "This link is not valid. Scan the QR code again." : "Could not create the order.";
        return show(msg, "error");
      }
      const order = await created.json();

      const put = await fetch(order.upload_url, {
        method: "PUT",
        headers: { "Content-Type": order.content_type },
        body: file,
      });
      if (!put.ok) return show("Upload failed. Try again.", "error");

      await poll(order.job_id);
    } catch (err) {
      show("Network error. Check your connection.", "error");
    } finally {
      sendBtn.disabled = false;
    }
  });
})();
