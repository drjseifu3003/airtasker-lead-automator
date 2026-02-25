# AI-Driven Lead Automation

## 1. Executive Summary

The goal of this project is to eliminate the manual Speed-to-Lead bottleneck for service professionals (carpenters) on platforms like Airtasker and HiPages. By deploying a Server-Side Shadow Agent, we will automate the detection, evaluation, and bidding process, securing customer contact details before a human competitor can even open the app.

## 2. The Problem Analysis

Manual lead acquisition is currently a failing strategy due to three primary frictions:

### **A. The Time Gap (The 2-Minute Rule)**

High-value leads on Airtasker are often claimed within 120 seconds. A carpenter mid-task cannot stop, clean their hands, and bid fast enough to compete with an automated system.

### **B. The Blind Financial Risk**

Platforms hide contact info until a lead is won oraccepted. This forces carpenters to spend credits or time on leads that might not be geographically or financially viable.

### **C. The Technical Barrier (The Moat)**

- No Public APIs: These platforms do not allow external software to connect.
- Anti-Bot Security: Cloudflare, Turnstile, and HCaptcha are used to block automated scripts.
- Account Risk: Poorly designed bots get accounts banned instantly.

## 3. The Proposed Solution: The Shadow User.

We will build a custom, server-side automation engine that mimics a human user with superhuman speed.

### **Phase 1: Real-Time Interception**

Instead of scraping the website (which is slow), our worker will perform Request Interception. It stays logged into the platform and listens to the WebSocket traffic. When a new job is posted, our server sees it the millisecond it hits the platform's database.

### **Phase 2: AI Decision Logic (GPT-4o-mini)**

We don't bid on everything. We pass the job data through a specialized AI prompt:

- Filter 1: Is the suburb within the carpenter's 15km radius?
- Filter 2: Does the Price-to-Effort ratio meet the $100/hr minimum?
- Filter 3: Does the description match the carpenter's skill set (e.g., Decking vs Painting)?

### **Phase 3: Stealth Execution & Bidding**

If the AI approves, the agent performs a Humanized Interaction:

- Stealth Headers: Using Playwright with a stealth plugin to bypass Cloudflare.
- Residential Proxies: Routing traffic through a local IP so it looks like the carpenter's home internet.
- Dynamic Bidding: AI writes a custom, persuasive message: "Hi, I'm local to [Suburb] and can fix your [Job] tomorrow morning. I've done 50+ similar jobs."

### **Phase 4: Instant Lead Handoff**

The moment the lead is won, and the phone number/email is revealed, the system triggers a Webhook. The carpenter receives an SMS or WhatsApp message with the customer's direct link.

## 4. The Invisible Worker Cloud Architecture

The most significant advantage of this system is that it requires no hardware and no active supervision from the carpenter.

- 24/7 Server-Side Execution: The automation is hosted on a high-speed Ubuntu VPS. Unlike a standard browser script, this does not require a laptop to be open or a phone to be active. It is a Ghost User that never sleeps.
- Headless Operation: We utilize Headless Chrome. This is a version of the browser that runs without a graphical user interface (no windows). It consumes minimal server resources while maintaining the same fingerprint as a real human user.
- Process Persistence: Using a manager like PM2, the system is self-healing. If the platform refreshes or the session drops, the system automatically re-establishes the connection in milliseconds, ensuring no lead window is missed.

## 5. Deep Dive: No-API Data Acquisition

If they don't have an API, how do we get the data?  **We use WebSocket and XHR Interception.

1. The Listener: Instead of scraping the HTML (which is slow and easily detected), our Playwright agent monitors the browser's Network Layer.
2. The Interception: Modern platforms update their job feeds using JSON data packets sent over WebSockets or background fetch requests.
3. The Result: Our agent catches these raw data packets the moment they arrive from the platform's server. This is actually faster than the mobile app's push notifications, giving the AI an immediate head start in analyzing and bidding.

## 6. Safety & Stealth: Preventing Account Bans

Because we are automating a human account, safety is the #1 priority.

- Residential Proxy Tunneling: We do not use Data Center IPs. We route all cloud traffic through a Static Residential Proxy based in the carpenter’s home city. To the platform, it looks like the carpenter is simply logged in from their home Wi-Fi.
- Fingerprint Randomization: Every time the browser starts, it generates a unique hardware fingerprint (Canvas, WebGL, User-Agent), making it impossible for the platform to link the bot to a single automated script.
- Human-Behavior Simulation: The bot doesn't move instantly. It mimics human mouse jitters, scrolls at variable speeds, and takes breaks to avoid looking like a 24/7 machine.

## 7. The Technical Stack

| **Category** | **Technology** | **Purpose** |
| --- | --- | --- |
| Automation | Playwright + SeleniumBase UC | Bypassing bot detection and mimicking Chrome. |
| Intelligence | OpenAI GPT-4o-mini API | High-speed text analysis and bid generation. |
| Network | Static Residential Proxies | Preventing account flags by staying on a local IP. |
| Infrastructure | Docker + Ubuntu VPS | Running 24/7 in the background with no downtime. |
| Bypass | CapSolver / 2Captcha API | Automatically solving any Captchas that appear. |