/**
 * FortiSales AI - Stage 5 Knowledge Base & RAG Console Controller
 */

let authToken = localStorage.getItem("fortisales_token") || "";

function showToast(msg, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = msg;
  toast.style.borderColor = isError ? "var(--danger)" : "var(--success)";
  toast.style.display = "block";
  setTimeout(() => { toast.style.display = "none"; }, 4000);
}

function saveAuthToken() {
  const tokenInput = document.getElementById("jwtToken");
  authToken = tokenInput.value.trim();
  localStorage.setItem("fortisales_token", authToken);
  showToast("Token saved. Refreshing knowledge base data...");
  loadActiveTabData();
}

function getAuthHeaders() {
  const headers = {};
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  return headers;
}

function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(panel => panel.classList.remove("active"));

  event.currentTarget.classList.add("active");
  const panel = document.getElementById(`tab-${tabId}`);
  if (panel) panel.classList.add("active");

  loadActiveTabData(tabId);
}

function loadActiveTabData(tabId) {
  if (!tabId) {
    const activePanel = document.querySelector(".tab-panel.active");
    if (!activePanel) return;
    tabId = activePanel.id.replace("tab-", "");
  }

  if (tabId === "company") loadCompanyInfo();
  else if (tabId === "products") loadProducts();
  else if (tabId === "faqs") loadFaqs();
  else if (tabId === "policies") loadPolicies();
  else if (tabId === "documents") loadDocuments();
}

// ---------------------------------------------------------------------------
// 1. Company Overview
// ---------------------------------------------------------------------------
async function loadCompanyInfo() {
  try {
    const res = await fetch("/api/v1/knowledge/company-info", { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    document.getElementById("comp-name").value = data.business_name || "";
    document.getElementById("comp-industry").value = data.industry || "";
    document.getElementById("comp-website").value = data.website || "";
    document.getElementById("comp-phone").value = data.contact_phone || "";
    document.getElementById("comp-email").value = data.contact_email || "";
    document.getElementById("comp-address").value = data.business_address || "";
    document.getElementById("comp-overview").value = data.company_overview || "";
    document.getElementById("comp-services").value = data.business_services || "";
    document.getElementById("comp-additional").value = data.additional_info || "";
  } catch (err) {
    console.error("Failed to load company info", err);
  }
}

async function saveCompanyInfo() {
  const payload = {
    business_name: document.getElementById("comp-name").value.trim(),
    industry: document.getElementById("comp-industry").value.trim(),
    website: document.getElementById("comp-website").value.trim(),
    contact_phone: document.getElementById("comp-phone").value.trim(),
    contact_email: document.getElementById("comp-email").value.trim(),
    business_address: document.getElementById("comp-address").value.trim(),
    company_overview: document.getElementById("comp-overview").value.trim(),
    business_services: document.getElementById("comp-services").value.trim(),
    additional_info: document.getElementById("comp-additional").value.trim(),
  };

  try {
    const res = await fetch("/api/v1/knowledge/company-info", {
      method: "PATCH",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    showToast("Company information saved and synchronized to Vector RAG!");
  } catch (err) {
    showToast("Error saving company info: " + err.message, true);
  }
}

// ---------------------------------------------------------------------------
// 2. Products & Services
// ---------------------------------------------------------------------------
async function loadProducts() {
  const tbody = document.getElementById("products-table-body");
  try {
    const res = await fetch("/api/v1/knowledge/products", { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(await res.text());
    const products = await res.json();
    if (products.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No products registered yet.</td></tr>';
      return;
    }
    tbody.innerHTML = products.map(p => {
      let tagClass = "tag-fixed";
      let tagText = "Fixed Price";
      if (p.pricing_type === "starting_from") { tagClass = "tag-starting"; tagText = "Starting From"; }
      else if (p.pricing_type === "quotation_required") { tagClass = "tag-quote"; tagText = "Quotation Required"; }

      const priceDisplay = p.price !== null ? `${p.price} ${p.currency}` : "Quote Only";
      return `
        <tr>
          <td><strong>${p.name}</strong><br><small style="color:var(--text-muted);">${p.description.slice(0, 50)}...</small></td>
          <td>${p.category}</td>
          <td><span class="tag ${tagClass}">${tagText}</span></td>
          <td>${priceDisplay}</td>
          <td>${p.is_available ? '<span style="color:var(--success)">Available</span>' : '<span style="color:var(--danger)">Unavailable</span>'}</td>
          <td>
            <button class="btn btn-danger" style="padding: 4px 8px; font-size: 12px;" onclick="deleteProduct('${p.id}')">Delete</button>
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="color: var(--danger);">Error loading products: ${err.message}</td></tr>`;
  }
}

async function openProductModal() {
  const name = prompt("Product or Service Name:");
  if (!name) return;
  const description = prompt("Description:") || "High-quality offering";
  const category = prompt("Category (default 'General'):") || "General";
  const pricingType = prompt("Pricing type: 'fixed', 'starting_from', or 'quotation_required':") || "fixed";
  let price = null;
  if (pricingType !== "quotation_required") {
    const pStr = prompt("Price (e.g. 99.00):");
    price = pStr ? parseFloat(pStr) : 0;
  }

  const payload = {
    name,
    description,
    category,
    pricing_type: pricingType,
    price: price,
    currency: "USD",
    is_available: true,
  };

  try {
    const res = await fetch("/api/v1/knowledge/products", {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    showToast("Product added and indexed in vector database!");
    loadProducts();
  } catch (err) {
    showToast("Error adding product: " + err.message, true);
  }
}

async function deleteProduct(id) {
  if (!confirm("Are you sure you want to delete this catalogue item?")) return;
  try {
    const res = await fetch(`/api/v1/knowledge/products/${id}`, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
    showToast("Product deleted from catalogue and vector RAG.");
    loadProducts();
  } catch (err) {
    showToast("Error deleting product: " + err.message, true);
  }
}

// ---------------------------------------------------------------------------
// 3. FAQs
// ---------------------------------------------------------------------------
async function loadFaqs() {
  const tbody = document.getElementById("faqs-table-body");
  try {
    const res = await fetch("/api/v1/knowledge/faqs", { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(await res.text());
    const faqs = await res.json();
    if (faqs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No FAQs registered yet.</td></tr>';
      return;
    }
    tbody.innerHTML = faqs.map(f => `
      <tr>
        <td><strong>${f.question}</strong><br><small style="color:var(--text-muted);">${f.answer.slice(0, 80)}...</small></td>
        <td>${f.category}</td>
        <td>${f.is_active ? '<span style="color:var(--success)">Active</span>' : 'Inactive'}</td>
        <td style="display: flex; gap: 6px;">
          <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 12px;" onclick="editFaq('${f.id}', '${encodeURIComponent(f.question)}', '${encodeURIComponent(f.answer)}', '${encodeURIComponent(f.category)}')">Edit</button>
          <button class="btn btn-danger" style="padding: 4px 8px; font-size: 12px;" onclick="deleteFaq('${f.id}')">Delete</button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" style="color: var(--danger);">Error loading FAQs: ${err.message}</td></tr>`;
  }
}

async function openFaqModal() {
  const question = prompt("FAQ Question:");
  if (!question) return;
  const answer = prompt("Standard Answer:");
  if (!answer) return;
  const category = prompt("Category (default 'General'):") || "General";

  try {
    const res = await fetch("/api/v1/knowledge/faqs", {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ question, answer, category, is_active: true }),
    });
    if (!res.ok) throw new Error(await res.text());
    showToast("FAQ added and indexed in vector database!");
    loadFaqs();
  } catch (err) {
    showToast("Error adding FAQ: " + err.message, true);
  }
}

async function editFaq(id, rawQ, rawA, rawCat) {
  const currentQ = decodeURIComponent(rawQ);
  const currentA = decodeURIComponent(rawA);
  const currentCat = decodeURIComponent(rawCat);

  const question = prompt("Edit FAQ Question:", currentQ);
  if (question === null) return;
  const answer = prompt("Edit Standard Answer:", currentA);
  if (answer === null) return;
  const category = prompt("Edit Category:", currentCat) || "General";

  try {
    const res = await fetch(`/api/v1/knowledge/faqs/${id}`, {
      method: "PATCH",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ question, answer, category }),
    });
    if (!res.ok) throw new Error(await res.text());
    showToast("FAQ updated and re-indexed in vector database!");
    loadFaqs();
  } catch (err) {
    showToast("Error updating FAQ: " + err.message, true);
  }
}

async function deleteFaq(id) {
  if (!confirm("Delete this FAQ?")) return;
  try {
    const res = await fetch(`/api/v1/knowledge/faqs/${id}`, { method: "DELETE", headers: getAuthHeaders() });
    if (!res.ok) throw new Error(await res.text());
    showToast("FAQ deleted.");
    loadFaqs();
  } catch (err) {
    showToast("Error: " + err.message, true);
  }
}

// ---------------------------------------------------------------------------
// 4. Policies
// ---------------------------------------------------------------------------
async function loadPolicies() {
  const tbody = document.getElementById("policies-table-body");
  try {
    const res = await fetch("/api/v1/knowledge/policies", { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(await res.text());
    const policies = await res.json();
    if (policies.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No policies registered yet.</td></tr>';
      return;
    }
    tbody.innerHTML = policies.map(p => `
      <tr>
        <td><span class="badge">${p.policy_type}</span></td>
        <td><strong>${p.title}</strong><br><small style="color:var(--text-muted);">${p.content.slice(0, 80)}...</small></td>
        <td>${p.is_active ? '<span style="color:var(--success)">Active</span>' : 'Inactive'}</td>
        <td>
          <button class="btn btn-danger" style="padding: 4px 8px; font-size: 12px;" onclick="deletePolicy('${p.id}')">Delete</button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" style="color: var(--danger);">Error loading policies: ${err.message}</td></tr>`;
  }
}

async function openPolicyModal() {
  const policy_type = prompt("Policy Type (e.g. cancellation, refund, reschedule, payment, warranty):");
  if (!policy_type) return;
  const title = prompt("Policy Title:");
  if (!title) return;
  const content = prompt("Policy Terms / Content:");
  if (!content) return;

  try {
    const res = await fetch("/api/v1/knowledge/policies", {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ policy_type, title, content, is_active: true }),
    });
    if (!res.ok) throw new Error(await res.text());
    showToast("Policy registered and vectorized!");
    loadPolicies();
  } catch (err) {
    showToast("Error adding policy: " + err.message, true);
  }
}

async function deletePolicy(id) {
  if (!confirm("Delete this policy?")) return;
  try {
    const res = await fetch(`/api/v1/knowledge/policies/${id}`, { method: "DELETE", headers: getAuthHeaders() });
    if (!res.ok) throw new Error(await res.text());
    showToast("Policy removed.");
    loadPolicies();
  } catch (err) {
    showToast("Error: " + err.message, true);
  }
}

// ---------------------------------------------------------------------------
// 5. Documents & Files Ingestion
// ---------------------------------------------------------------------------
async function loadDocuments() {
  const tbody = document.getElementById("documents-table-body");
  try {
    const res = await fetch("/api/v1/knowledge/documents", { headers: getAuthHeaders() });
    if (!res.ok) throw new Error(await res.text());
    const docs = await res.json();
    if (docs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No documents ingested yet.</td></tr>';
      return;
    }
    tbody.innerHTML = docs.map(d => `
      <tr>
        <td><strong>${d.title}</strong><br><small style="color:var(--text-muted);">${d.file_path || 'Direct input'}</small></td>
        <td><span class="badge">${d.document_type}</span></td>
        <td>${d.chunk_count} chunks</td>
        <td>${new Date(d.created_at).toLocaleDateString()}</td>
        <td style="display: flex; gap: 6px;">
          <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 12px;" onclick="retryDocument('${d.id}')">Retry</button>
          <button class="btn btn-danger" style="padding: 4px 8px; font-size: 12px;" onclick="deleteDocument('${d.id}')">Delete</button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="color: var(--danger);">Error loading documents: ${err.message}</td></tr>`;
  }
}

async function uploadDocument() {
  const fileInput = document.getElementById("doc-file-input");
  const titleInput = document.getElementById("doc-title-input");
  const typeInput = document.getElementById("doc-type-input");

  if (!fileInput.files || fileInput.files.length === 0) {
    showToast("Please select a file to upload.", true);
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  if (titleInput.value.trim()) {
    formData.append("title", titleInput.value.trim());
  }
  formData.append("document_type", typeInput.value);

  try {
    showToast("Parsing, chunking, and vectorizing document...");
    const res = await fetch("/api/v1/knowledge/documents/upload", {
      method: "POST",
      headers: getAuthHeaders(),
      body: formData,
    });
    if (!res.ok) throw new Error(await res.text());
    const doc = await res.json();
    showToast(`Ingested '${doc.title}' (${doc.chunk_count} chunks embedded)!`);
    fileInput.value = "";
    titleInput.value = "";
    loadDocuments();
  } catch (err) {
    showToast("Upload failed: " + err.message, true);
  }
}

async function retryDocument(id) {
  try {
    showToast("Retrying document re-chunking and vector embedding...");
    const res = await fetch(`/api/v1/knowledge/documents/${id}/retry`, {
      method: "POST",
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
    const doc = await res.json();
    showToast(`Successfully re-indexed '${doc.title}' (${doc.chunk_count} chunks embedded)!`);
    loadDocuments();
  } catch (err) {
    showToast("Retry failed: " + err.message, true);
  }
}

async function deleteDocument(id) {
  if (!confirm("Delete this document and all its vector chunks?")) return;
  try {
    const res = await fetch(`/api/v1/knowledge/documents/${id}`, { method: "DELETE", headers: getAuthHeaders() });
    if (!res.ok) throw new Error(await res.text());
    showToast("Document deleted.");
    loadDocuments();
  } catch (err) {
    showToast("Error: " + err.message, true);
  }
}

// ---------------------------------------------------------------------------
// 6. RAG Semantic Query Tester
// ---------------------------------------------------------------------------
async function testSemanticQuery() {
  const query = document.getElementById("test-query-input").value.trim();
  const threshold = parseFloat(document.getElementById("test-threshold-input").value) || 0.2;
  const limit = parseInt(document.getElementById("test-limit-input").value) || 4;
  const container = document.getElementById("test-results-container");

  if (!query) {
    showToast("Please enter a search query.", true);
    return;
  }

  container.innerHTML = "<p style='color: var(--text-muted);'>Executing vector search against pgvector HNSW index...</p>";

  try {
    const res = await fetch("/api/v1/knowledge/query", {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ query, score_threshold: threshold, limit }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    if (data.results.length === 0) {
      container.innerHTML = `<p style="color: var(--warning);">No chunks matched query with similarity &ge; ${threshold}.</p>`;
      return;
    }

    container.innerHTML = data.results.map((r, i) => `
      <div class="result-card">
        <div class="result-header">
          <span>#${i + 1} <strong>${r.document_title}</strong> (${r.document_type})</span>
          <span class="score-badge">Cosine Similarity: ${(r.score * 100).toFixed(1)}%</span>
        </div>
        <p style="white-space: pre-wrap; font-size: 13px; line-height: 1.5;">${r.content}</p>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = `<p style="color: var(--danger);">Search error: ${err.message}</p>`;
  }
}

// Initial setup
window.addEventListener("DOMContentLoaded", () => {
  if (authToken) {
    document.getElementById("jwtToken").value = authToken;
    loadActiveTabData("company");
  }
});
