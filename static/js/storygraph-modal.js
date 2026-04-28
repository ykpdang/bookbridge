var storygraphModalState = {
    absId: null,
    bookData: null
};

function linkStorygraph(event) {
    event.stopPropagation();
    storygraphModalState.absId = event.currentTarget.dataset.absId;
    storygraphModalState.bookData = null;
    openStorygraphModal();
    autoResolveStorygraphBook();
}

function openStorygraphModal() {
    document.getElementById('storygraph-modal').style.display = 'flex';
    showStorygraphState('loading');
}

function closeStorygraphModal() {
    document.getElementById('storygraph-modal').style.display = 'none';
}

function showStorygraphState(state) {
    ['loading', 'found', 'manual', 'error'].forEach(function(s) {
        document.getElementById('sg-' + s).style.display = (s === state) ? 'block' : 'none';
    });
    document.getElementById('sg-link-btn').disabled = (state !== 'found');
}

async function autoResolveStorygraphBook() {
    showStorygraphState('loading');
    try {
        const resp = await fetch('/api/storygraph/resolve?abs_id=' + storygraphModalState.absId);
        const data = await resp.json();
        if (data && data.found) {
            displayStorygraphBook(data);
            return;
        }
        if (!resp.ok) {
            document.getElementById('sg-error-msg').textContent = (data && data.message) || 'Search failed';
            showStorygraphState('error');
            return;
        }
        showStorygraphState('manual');
    } catch (err) {
        showStorygraphState('manual');
    }
}

function showStorygraphManualInput() {
    showStorygraphState('manual');
    document.getElementById('sg-input').value = '';
    document.getElementById('sg-input').focus();
}

async function resolveStorygraphManualInput() {
    const input = document.getElementById('sg-input').value.trim();
    if (!input) return;
    showStorygraphState('loading');
    try {
        const resp = await fetch('/api/storygraph/resolve?abs_id=' + storygraphModalState.absId + '&input=' + encodeURIComponent(input));
        const data = await resp.json();
        if (data && data.found) {
            displayStorygraphBook(data);
            return;
        }
        document.getElementById('sg-error-msg').textContent = (data && data.message) || 'Book not found';
        showStorygraphState('error');
    } catch (err) {
        document.getElementById('sg-error-msg').textContent = 'Search failed';
        showStorygraphState('error');
    }
}

function displayStorygraphBook(data) {
    storygraphModalState.bookData = data;
    document.getElementById('sg-title').textContent = data.title || 'Unknown Title';
    document.getElementById('sg-author').textContent = data.author || 'Unknown Author';

    var link = document.getElementById('sg-found-url');
    link.href = data.url || '#';
    link.textContent = data.linked ? 'Open current StoryGraph link' : 'Open in StoryGraph';

    showStorygraphState('found');
}

async function linkSelectedStorygraphBook() {
    const data = storygraphModalState.bookData;
    if (!data || !data.book_id) {
        return;
    }

    const button = document.getElementById('sg-link-btn');
    button.disabled = true;
    button.textContent = 'Linking...';

    try {
        const resp = await fetch('/link-storygraph/' + storygraphModalState.absId, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                book_id: data.book_id,
                title: data.title || '',
                author: data.author || '',
                url: data.url || ''
            })
        });

        if (!resp.ok) {
            const payload = await resp.json().catch(function() { return {}; });
            throw new Error(payload.error || 'Link failed');
        }

        closeStorygraphModal();
        window.location.reload();
    } catch (err) {
        document.getElementById('sg-error-msg').textContent = err.message || 'Link failed';
        showStorygraphState('error');
    } finally {
        button.disabled = false;
        button.textContent = 'Link Book';
    }
}
