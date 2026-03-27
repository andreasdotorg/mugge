/**
 * D-020 Web UI — Graph view module (US-064 Phase 3).
 *
 * Data-driven rendering from /api/v1/graph/topology.
 * Fetches topology (nodes, links, internal filter-chain structure) and
 * renders a left-to-right signal-flow SVG diagram:
 *   Sources (col 0) -> DSP (col 1) -> Outputs (col 2)
 *
 * The convolver node is expanded to show its internal topology
 * (convolver + gain nodes from the SPA config parser).
 *
 * GM-managed nodes/links are highlighted with brighter borders/colors.
 * Auto-refreshes at ~2Hz via polling when the graph tab is visible.
 *
 * No external dependencies. Pure SVG + CSS transitions.
 */

"use strict";

(function () {

    // -- Layout constants --

    var SVG_W = 960;
    var SVG_H = 480;
    var NODE_W = 160;
    var NODE_W_NARROW = 120;
    var HEADER_H = 24;
    var PORT_ROW_H = 22;
    var PORT_PAD = 8;
    var PORT_R = 6;
    var NODE_R = 6;
    var NODE_GAP = 24;
    var COL_GAP = 180;   // horizontal gap between columns

    var NS = "http://www.w3.org/2000/svg";

    // -- Node type colors (resolved from CSS vars at init) --

    var NODE_COLORS = null;

    function initNodeColors() {
        var cv = PiAudio.cssVar;
        NODE_COLORS = {
            source:  cv("--group-app"),
            dsp:     cv("--group-dsp"),
            gain:    cv("--group-gain"),
            output:  cv("--group-hw"),
            capture: cv("--gv-color-capture"),
            utility: cv("--gv-color-utility"),
            other:   cv("--group-main")
        };
    }

    // -- State --

    var svgEl = null;
    var pollTimer = null;
    var lastTopologyJSON = null;
    var POLL_INTERVAL_MS = 5000;  // F-127: reduced from 2s to 5s to cut pw-dump subprocess rate

    // Pan+zoom state (F-085 #7)
    var isPanning = false;
    var panStartX = 0;
    var panStartY = 0;
    var curVB = { x: 0, y: 0, w: 860, h: 480 };
    var fitVB = { w: 860, h: 480 };  // reference size from last fitViewBox
    var ZOOM_MIN = 0.3;
    var ZOOM_MAX = 3.0;

    // Touch state for pinch-to-zoom
    var lastTouchDist = 0;
    var lastTouchMid = { x: 0, y: 0 };

    // -- SVG helpers --

    function svgCreate(tag, attrs) {
        var el = document.createElementNS(NS, tag);
        if (attrs) {
            for (var k in attrs) {
                el.setAttribute(k, attrs[k]);
            }
        }
        return el;
    }

    function svgText(x, y, text, cls, extraAttrs) {
        var el = svgCreate("text", { x: x, y: y, "class": cls });
        el.textContent = text;
        if (extraAttrs) {
            for (var k in extraAttrs) {
                el.setAttribute(k, extraAttrs[k]);
            }
        }
        return el;
    }

    // -- Marker definitions (arrowheads) --

    function buildDefs() {
        var defs = svgCreate("defs");

        var markers = [
            { id: "gv-arrow",      cls: "gv-arrowhead" },
            { id: "gv-arrow-blue", cls: "gv-arrowhead-blue" },
            { id: "gv-arrow-red",  cls: "gv-arrowhead-red" },
            { id: "gv-arrow-gm",   cls: "gv-arrowhead-gm" }
        ];

        for (var i = 0; i < markers.length; i++) {
            var m = svgCreate("marker", {
                id: markers[i].id, markerWidth: "8", markerHeight: "6",
                refX: "8", refY: "3", orient: "auto", markerUnits: "userSpaceOnUse"
            });
            m.appendChild(svgCreate("path", {
                d: "M0,0 L8,3 L0,6 Z", "class": markers[i].cls
            }));
            defs.appendChild(m);
        }

        return defs;
    }

    // -- Node builder --

    function buildNode(opts) {
        var w = opts.narrow ? NODE_W_NARROW : NODE_W;
        var maxPorts = Math.max(
            opts.inputs ? opts.inputs.length : 0,
            opts.outputs ? opts.outputs.length : 0
        );
        var portAreaH = maxPorts > 0 ? PORT_PAD + maxPorts * PORT_ROW_H + PORT_PAD : 40;
        var h = HEADER_H + portAreaH;
        var x = opts.x - w / 2;
        var y = opts.y;

        var stateClass = "gv-node--" + (opts.state || "active");
        var managedClass = opts.gm_managed ? " gv-node--managed" : "";
        var g = svgCreate("g", {
            id: opts.id || "",
            "class": "gv-node " + stateClass + managedClass,
            transform: "translate(" + x + "," + y + ")"
        });

        // Main rect
        g.appendChild(svgCreate("rect", {
            "class": "gv-node-rect",
            x: 0, y: 0, width: w, height: h, rx: NODE_R, ry: NODE_R
        }));

        // Header bar
        var color = NODE_COLORS[opts.colorKey] || NODE_COLORS.other;
        g.appendChild(svgCreate("rect", {
            "class": "gv-node-header",
            x: 0, y: 0, width: w, height: HEADER_H,
            rx: NODE_R, ry: NODE_R,
            fill: color
        }));
        // Mask bottom corners of header
        g.appendChild(svgCreate("rect", {
            "class": "gv-node-header-mask",
            x: 0, y: HEADER_H - NODE_R, width: w, height: NODE_R
        }));

        // Title (F-085 #9: truncate with ellipsis + tooltip for overflow)
        var maxChars = opts.narrow ? 12 : 17;
        var displayLabel = opts.label;
        if (displayLabel.length > maxChars) {
            displayLabel = displayLabel.substring(0, maxChars - 1) + "\u2026";
        }
        var labelEl = svgText(w / 2, HEADER_H / 2, displayLabel, "gv-node-label");
        if (displayLabel !== opts.label) {
            var titleEl = svgCreate("title");
            titleEl.textContent = opts.label;
            labelEl.appendChild(titleEl);
        }
        g.appendChild(labelEl);

        // Sublabel (description) — truncate defensively (F-085 #9)
        if (opts.sublabel) {
            var subMax = opts.narrow ? 16 : 22;
            var displaySub = opts.sublabel;
            if (displaySub.length > subMax) {
                displaySub = displaySub.substring(0, subMax - 1) + "\u2026";
            }
            var subEl = svgText(w / 2, HEADER_H + 14, displaySub, "gv-node-sublabel");
            if (displaySub !== opts.sublabel) {
                var subTitle = svgCreate("title");
                subTitle.textContent = opts.sublabel;
                subEl.appendChild(subTitle);
            }
            g.appendChild(subEl);
        }

        // Ports
        var inputPorts = [];
        var outputPorts = [];
        var portStartY = HEADER_H + PORT_PAD;

        if (opts.inputs && opts.inputs.length > 0) {
            var inOffset = 0;
            if (opts.outputs && opts.inputs.length < opts.outputs.length) {
                inOffset = (opts.outputs.length - opts.inputs.length) * PORT_ROW_H / 2;
            }
            for (var i = 0; i < opts.inputs.length; i++) {
                var py = portStartY + inOffset + i * PORT_ROW_H + PORT_ROW_H / 2;
                g.appendChild(svgCreate("circle", {
                    "class": "gv-port gv-port--input gv-port--idle",
                    cx: 0, cy: py, r: PORT_R,
                    "data-port": opts.inputs[i]
                }));
                g.appendChild(svgText(14, py, shortPortName(opts.inputs[i]), "gv-port-label gv-port-label--input"));
                inputPorts.push({ label: opts.inputs[i], cx: x, cy: y + py });
            }
        }

        if (opts.outputs && opts.outputs.length > 0) {
            var outOffset = 0;
            if (opts.inputs && opts.outputs.length < opts.inputs.length) {
                outOffset = (opts.inputs.length - opts.outputs.length) * PORT_ROW_H / 2;
            }
            for (var j = 0; j < opts.outputs.length; j++) {
                var py2 = portStartY + outOffset + j * PORT_ROW_H + PORT_ROW_H / 2;
                g.appendChild(svgCreate("circle", {
                    "class": "gv-port gv-port--output gv-port--idle",
                    cx: w, cy: py2, r: PORT_R,
                    "data-port": opts.outputs[j]
                }));
                g.appendChild(svgText(w - 14, py2, shortPortName(opts.outputs[j]), "gv-port-label gv-port-label--output"));
                outputPorts.push({ label: opts.outputs[j], cx: x + w, cy: y + py2 });
            }
        }

        return { g: g, inputPorts: inputPorts, outputPorts: outputPorts, width: w, height: h };
    }

    // -- Link builder --

    function buildLink(x1, y1, x2, y2, cls, markerId) {
        var dx = x2 - x1;
        var d = "M " + x1 + " " + y1 +
                " C " + (x1 + dx * 0.4) + " " + y1 + "," +
                (x2 - dx * 0.4) + " " + y2 + "," +
                x2 + " " + y2;
        var attrs = { d: d, "class": "gv-link " + cls };
        if (markerId) {
            attrs["marker-end"] = "url(#" + markerId + ")";
        }
        return svgCreate("path", attrs);
    }

    // -- Node classification --
    // Classifies PipeWire nodes into rendering columns.
    // Real pw-dump media.class values observed on Pi:
    //   Stream/Output/Audio  — app playback (Mixxx, Reaper, signal-gen)
    //   Stream/Input/Audio   — app capture (pcm-bridge, recording)
    //   Audio/Sink           — hardware playback device or filter-chain sink
    //   Audio/Source         — hardware capture device (UMIK-1, ADA8200 inputs)
    //   Audio/Duplex         — duplex ALSA device (USBStreamer)
    //   Midi/Bridge          — MIDI device (Hercules, APCmini, Nektar)
    //   Video/Source         — camera (skip)

    function classifyNode(node) {
        var mc = (node.media_class || "").toLowerCase();
        var name = (node.name || "").toLowerCase();

        // Skip non-audio nodes
        if (mc.indexOf("midi") !== -1) return "skip";
        if (mc.indexOf("video") !== -1) return "skip";

        // Filter-chain convolver = DSP (center column)
        if (name === "pi4audio-convolver") return "dsp";

        // GraphManager internal node — skip from graph
        if (name.indexOf("graphmanager") !== -1) return "skip";

        // App playback streams = sources (left column)
        if (mc.indexOf("stream/output") !== -1) return "source";

        // App capture streams (pcm-bridge, signal-gen recorder) = utility
        if (mc.indexOf("stream/input") !== -1) return "utility";

        // Hardware capture devices (UMIK-1, ADA8200 inputs) = capture
        if (mc === "audio/source") return "capture";

        // Hardware playback sinks (USBStreamer output, HDMI, headphones)
        if (mc === "audio/sink") return "output";

        // Duplex devices (USBStreamer appears as Audio/Duplex on some configs)
        if (mc === "audio/duplex") return "output";

        return "other";
    }

    function colorKeyForClass(cls) {
        return NODE_COLORS[cls] ? cls : "other";
    }

    // -- Internal topology expansion --

    function buildInternalColumn(internal, parentX, parentY, parentW) {
        // internal = {nodes, links, inputs, outputs}
        // Build two sub-columns within the DSP column:
        //   convolver nodes (left) and gain nodes (right)
        var convolvers = [];
        var gains = [];
        var nodesByName = {};

        for (var i = 0; i < internal.nodes.length; i++) {
            var n = internal.nodes[i];
            nodesByName[n.name] = n;
            if (n.label === "convolver") {
                convolvers.push(n);
            } else if (n.label === "linear") {
                gains.push(n);
            }
        }

        // Layout: convolvers on left sub-column, gains on right sub-column
        var subColGap = 160;
        var convX = parentX - subColGap / 2;
        var gainX = parentX + subColGap / 2;

        var builtConvs = [];
        var builtGains = [];

        // Stack convolvers vertically
        var convTotalH = convolvers.length * (HEADER_H + PORT_PAD + PORT_ROW_H + PORT_PAD) +
                         (convolvers.length - 1) * NODE_GAP;
        var convStartY = parentY - convTotalH / 2;

        for (var c = 0; c < convolvers.length; c++) {
            var cy = convStartY + c * (HEADER_H + PORT_PAD + PORT_ROW_H + PORT_PAD + NODE_GAP);
            var cn = buildNode({
                id: "gv-int-" + convolvers[c].name,
                label: convolvers[c].name.replace("conv_", "").replace("_", " "),
                colorKey: "dsp",
                x: convX, y: cy,
                inputs: ["In"], outputs: ["Out"],
                state: "active",
                gm_managed: true
            });
            builtConvs.push({ node: cn, name: convolvers[c].name });
        }

        // Stack gains vertically (same y positions as convolvers)
        var gainTotalH = gains.length * (HEADER_H + PORT_PAD + PORT_ROW_H + PORT_PAD) +
                         (gains.length - 1) * NODE_GAP;
        var gainStartY = parentY - gainTotalH / 2;

        for (var g = 0; g < gains.length; g++) {
            var gy = gainStartY + g * (HEADER_H + PORT_PAD + PORT_ROW_H + PORT_PAD + NODE_GAP);
            var mult = "";
            if (gains[g].control && gains[g].control.Mult !== undefined) {
                var multVal = gains[g].control.Mult;
                if (multVal > 0) {
                    var db = 20 * Math.log10(multVal);
                    mult = db.toFixed(1) + " dB";
                } else {
                    mult = "-inf dB";
                }
            }
            var gn = buildNode({
                id: "gv-int-" + gains[g].name,
                label: gains[g].name.replace("gain_", "").replace("_", " "),
                sublabel: mult,
                colorKey: "gain",
                x: gainX, y: gy,
                inputs: ["In"], outputs: ["Out"],
                narrow: true,
                state: "active",
                gm_managed: true
            });
            builtGains.push({ node: gn, name: gains[g].name });
        }

        // Build internal links (convolver Out -> gain In)
        var intLinks = [];
        for (var li = 0; li < internal.links.length; li++) {
            var lnk = internal.links[li];
            var srcBuilt = findBuiltNode(builtConvs, builtGains, lnk.output_node);
            var dstBuilt = findBuiltNode(builtConvs, builtGains, lnk.input_node);
            if (srcBuilt && dstBuilt) {
                var outPort = findPort(srcBuilt.node.outputPorts, lnk.output_port);
                var inPort = findPort(dstBuilt.node.inputPorts, lnk.input_port);
                if (outPort && inPort) {
                    intLinks.push(buildLink(
                        outPort.cx, outPort.cy,
                        inPort.cx, inPort.cy,
                        "gv-link--connected gv-link--managed", "gv-arrow-gm"
                    ));
                }
            }
        }

        // Build entry/exit port maps for link routing
        var entryPorts = {};  // port index -> input port of first convolver node
        for (var ei = 0; ei < internal.inputs.length; ei++) {
            var inp = internal.inputs[ei];
            var entryBuilt = findBuiltNode(builtConvs, builtGains, inp.node);
            if (entryBuilt) {
                var ep = findPort(entryBuilt.node.inputPorts, inp.port);
                if (ep) entryPorts[ei] = ep;
            }
        }

        var exitPorts = {};  // port index -> output port of last gain node
        for (var xi = 0; xi < internal.outputs.length; xi++) {
            var outp = internal.outputs[xi];
            var exitBuilt = findBuiltNode(builtConvs, builtGains, outp.node);
            if (exitBuilt) {
                var xp = findPort(exitBuilt.node.outputPorts, outp.port);
                if (xp) exitPorts[xi] = xp;
            }
        }

        return {
            convNodes: builtConvs,
            gainNodes: builtGains,
            internalLinks: intLinks,
            entryPorts: entryPorts,
            exitPorts: exitPorts,
            convX: convX,
            gainX: gainX
        };
    }

    function findBuiltNode(convs, gains, name) {
        for (var i = 0; i < convs.length; i++) {
            if (convs[i].name === name) return convs[i];
        }
        for (var j = 0; j < gains.length; j++) {
            if (gains[j].name === name) return gains[j];
        }
        return null;
    }

    function findPort(ports, label) {
        for (var i = 0; i < ports.length; i++) {
            if (ports[i].label === label) return ports[i];
        }
        // Fallback: match by substring
        for (var j = 0; j < ports.length; j++) {
            if (label.indexOf(ports[j].label) !== -1 || ports[j].label.indexOf(label) !== -1) {
                return ports[j];
            }
        }
        return ports.length > 0 ? ports[0] : null;
    }

    // -- Name shortening helpers --

    function shortName(name) {
        // Shorten long PipeWire node names for display:
        //   "alsa_output.usb-miniDSP_USBStreamer_B..." -> "USBStreamer B"
        //   "alsa_input.usb-miniDSP_UMIK-1..." -> "UMIK-1"
        if (!name) return "?";
        // Strip common ALSA prefixes
        var s = name.replace(/^alsa_(output|input|playback|capture)\./i, "");
        // Extract device name from USB path
        var usbMatch = s.match(/usb-([^.]+)/);
        if (usbMatch) {
            s = usbMatch[1].replace(/_/g, " ");
        }
        // Trim trailing serial numbers / long suffixes
        s = s.replace(/-\d{10,}.*$/, "");
        return s || name;
    }

    function shortPortName(name) {
        // Shorten port names for readability:
        //   "playback_AUX0" -> "AUX0"
        //   "capture_AUX0" -> "AUX0"
        //   "monitor_FL" -> "mon FL"
        //   "output_FL" -> "FL"
        //   "input_0" -> "in 0"
        if (!name) return "?";
        if (name.indexOf("playback_") === 0) return name.substring(9);
        if (name.indexOf("capture_") === 0) return name.substring(8);
        if (name.indexOf("monitor_") === 0) return "mon " + name.substring(8);
        if (name.indexOf("output_") === 0) return name.substring(7);
        return name;
    }

    // -- Port name extraction from node --

    function guessInputPorts(node) {
        // For the convolver node with internal topology, use the internal inputs
        if (node.internal && node.internal.inputs) {
            return node.internal.inputs.map(function (p) {
                return p.port || p.node;
            });
        }
        // Generic: number ports based on media_class
        var mc = (node.media_class || "").toLowerCase();
        if (mc.indexOf("sink") !== -1) return ["in_0", "in_1"];
        return [];
    }

    function guessOutputPorts(node) {
        if (node.internal && node.internal.outputs) {
            return node.internal.outputs.map(function (p) {
                return p.port || p.node;
            });
        }
        var mc = (node.media_class || "").toLowerCase();
        if (mc.indexOf("stream/output") !== -1) return ["out_0", "out_1"];
        if (mc.indexOf("source") !== -1) return ["out_0", "out_1"];
        return [];
    }

    // -- Topology rendering --

    function renderTopology(data) {
        if (!svgEl) return;

        // Clear existing content (keep defs)
        var children = svgEl.childNodes;
        for (var i = children.length - 1; i >= 0; i--) {
            if (children[i].tagName !== "defs") {
                svgEl.removeChild(children[i]);
            }
        }

        var group = svgCreate("g", { "class": "gv-template-group" });

        // Mode label
        var modeLabel = svgText(12, 18, (data.mode || "").toUpperCase(), "gv-mode-label");
        modeLabel.id = "gv-mode-label";
        svgEl.appendChild(modeLabel);

        // Classify nodes into columns:
        //   captures (hw input) | sources (app output) | DSP | outputs (hw sink) | utility (app input)
        // Captures and utility share the left/right edges; sources and outputs
        // are the primary signal-flow columns.
        var captures = [];
        var sources = [];
        var dspNodes = [];
        var outputs = [];
        var utilities = [];
        var nodeMap = {};  // id -> node data

        for (var n = 0; n < data.nodes.length; n++) {
            var node = data.nodes[n];
            nodeMap[node.id] = node;
            var cls = classifyNode(node);
            if (cls === "capture") captures.push(node);
            else if (cls === "source") sources.push(node);
            else if (cls === "dsp") dspNodes.push(node);
            else if (cls === "output") outputs.push(node);
            else if (cls === "utility") utilities.push(node);
            // skip "skip" and "other" nodes
        }

        // Merge captures into sources column (same left column, captures above)
        var leftNodes = captures.concat(sources);

        // Calculate column X positions
        var hasInternal = false;
        for (var di = 0; di < dspNodes.length; di++) {
            if (dspNodes[di].internal) { hasInternal = true; break; }
        }

        var colX;
        if (hasInternal) {
            // 4 sub-columns: source, conv, gain, output
            colX = [80, 280, 440, 640];
        } else {
            // 3 columns: source, dsp, output
            colX = [80, 320, 560];
        }

        // Merge utilities into right column (outputs above, utilities below)
        var rightNodes = outputs.concat(utilities);

        // F-085 #1: Pre-compute column heights to find a centerY that
        // prevents overlap. Fixed SVG_H/2 caused overlap with real data.
        var leftTotalH = 0;
        for (var sp = 0; sp < leftNodes.length; sp++) {
            var srcP = leftNodes[sp];
            var srcCls = classifyNode(srcP);
            // Captures have inputs not outputs; sources have outputs
            var srcPortsP = (srcCls === "capture")
                ? collectPortNames(data.links, srcP.id, "input")
                : collectPortNames(data.links, srcP.id, "output");
            if (srcPortsP.length === 0) srcPortsP = ["port_0", "port_1"];
            var srcHP = HEADER_H + PORT_PAD + Math.max(1, srcPortsP.length) * PORT_ROW_H + PORT_PAD;
            leftTotalH += srcHP + (sp > 0 ? NODE_GAP : 0);
        }
        var rightTotalH = 0;
        for (var op = 0; op < rightNodes.length; op++) {
            var outP = rightNodes[op];
            var outCls = classifyNode(outP);
            // Outputs have inputs; utilities have outputs (they capture audio)
            var outPortsP = (outCls === "utility")
                ? collectPortNames(data.links, outP.id, "input")
                : collectPortNames(data.links, outP.id, "input");
            if (outPortsP.length === 0) outPortsP = ["port_0", "port_1"];
            var outHP = HEADER_H + PORT_PAD + Math.max(1, outPortsP.length) * PORT_ROW_H + PORT_PAD;
            rightTotalH += outHP + (op > 0 ? NODE_GAP : 0);
        }
        // Internal expansion: 4 convolver + 4 gain nodes stacked
        var dspTotalH = hasInternal
            ? 4 * (HEADER_H + PORT_PAD + PORT_ROW_H + PORT_PAD) + 3 * NODE_GAP
            : 120;
        var maxColH = Math.max(leftTotalH, rightTotalH, dspTotalH);
        var centerY = Math.max(SVG_H / 2, maxColH / 2 + NODE_GAP);

        // Build left-column nodes (captures + sources)
        var builtSources = [];
        var srcY = centerY - leftTotalH / 2;
        for (var s2 = 0; s2 < leftNodes.length; s2++) {
            var src2 = leftNodes[s2];
            var src2Cls = classifyNode(src2);
            var src2ColorKey = colorKeyForClass(src2Cls);
            // Captures show input ports (they receive audio from hardware);
            // sources show output ports (they send audio to the graph)
            var srcIns2 = (src2Cls === "capture")
                ? collectPortNames(data.links, src2.id, "input")
                : [];
            var srcOuts2 = (src2Cls === "capture")
                ? collectPortNames(data.links, src2.id, "output")
                : collectPortNames(data.links, src2.id, "output");
            if (srcOuts2.length === 0 && srcIns2.length === 0) srcOuts2 = ["out_0", "out_1"];
            var built = buildNode({
                id: "gv-node-" + src2.id,
                label: src2.description || shortName(src2.name),
                colorKey: src2ColorKey,
                x: colX[0], y: srcY,
                inputs: srcIns2,
                outputs: srcOuts2,
                state: src2.state === "running" ? "active" : "absent",
                gm_managed: src2.gm_managed
            });
            builtSources.push({ data: src2, built: built });
            srcY += built.height + NODE_GAP;
        }

        // Build right-column nodes (outputs + utilities)
        var builtOutputs = [];
        var outY = centerY - rightTotalH / 2;
        var outColIdx = hasInternal ? 3 : 2;
        for (var o2 = 0; o2 < rightNodes.length; o2++) {
            var out2 = rightNodes[o2];
            var out2Cls = classifyNode(out2);
            var out2ColorKey = colorKeyForClass(out2Cls);
            var outIns2 = collectPortNames(data.links, out2.id, "input");
            var outOuts2 = (out2Cls === "utility")
                ? collectPortNames(data.links, out2.id, "output")
                : [];
            if (outIns2.length === 0 && outOuts2.length === 0) outIns2 = ["in_0", "in_1"];
            var builtOut = buildNode({
                id: "gv-node-" + out2.id,
                label: out2.description || shortName(out2.name),
                colorKey: out2ColorKey,
                x: colX[outColIdx], y: outY,
                inputs: outIns2,
                outputs: outOuts2,
                state: out2.state === "running" ? "active" : "absent",
                gm_managed: out2.gm_managed
            });
            builtOutputs.push({ data: out2, built: builtOut });
            outY += builtOut.height + NODE_GAP;
        }

        // Build DSP nodes (with internal expansion)
        var builtDsp = [];
        var internalExpansion = null;

        for (var d = 0; d < dspNodes.length; d++) {
            var dsp = dspNodes[d];
            if (dsp.internal && hasInternal) {
                // Expand internal topology into convolver + gain sub-columns
                var intCenterY = centerY;
                internalExpansion = buildInternalColumn(
                    dsp.internal, (colX[1] + colX[2]) / 2, intCenterY, NODE_W
                );
                builtDsp.push({ data: dsp, internal: internalExpansion });
            } else {
                // Simple DSP node
                var dspIns = collectPortNames(data.links, dsp.id, "input");
                var dspOuts = collectPortNames(data.links, dsp.id, "output");
                if (dspIns.length === 0) dspIns = guessInputPorts(dsp);
                if (dspOuts.length === 0) dspOuts = guessOutputPorts(dsp);
                var dspIdx = hasInternal ? 1 : 1;
                var builtDspNode = buildNode({
                    id: "gv-node-" + dsp.id,
                    label: dsp.description || dsp.name,
                    colorKey: "dsp",
                    x: colX[dspIdx], y: centerY - 60,
                    inputs: dspIns,
                    outputs: dspOuts,
                    state: dsp.state === "running" ? "active" : "absent",
                    gm_managed: dsp.gm_managed
                });
                builtDsp.push({ data: dsp, built: builtDspNode });
            }
        }

        // Build links layer
        var linksGroup = svgCreate("g");

        for (var li = 0; li < data.links.length; li++) {
            var link = data.links[li];
            var linkCls = "gv-link--connected";
            var markerId = "gv-arrow";

            if (link.state === "error" || link.state === "failed") {
                linkCls = "gv-link--failed";
                markerId = "gv-arrow-red";
            }

            if (link.gm_managed) {
                linkCls += " gv-link--managed";
                if (markerId === "gv-arrow") markerId = "gv-arrow-gm";
            }

            // Resolve source port
            var srcPort = resolveOutputPort(
                link.output_node, link.output_port,
                builtSources, builtDsp, builtOutputs, internalExpansion
            );
            // Resolve destination port
            var dstPort = resolveInputPort(
                link.input_node, link.input_port,
                builtSources, builtDsp, builtOutputs, internalExpansion
            );

            if (srcPort && dstPort) {
                linksGroup.appendChild(buildLink(
                    srcPort.cx, srcPort.cy,
                    dstPort.cx, dstPort.cy,
                    linkCls, markerId
                ));
            }
        }

        // Append in SVG painter's order: nodes first, then links on top
        // (F-054: links must render above nodes so connection paths are visible)

        // Append source nodes
        for (var as = 0; as < builtSources.length; as++) {
            group.appendChild(builtSources[as].built.g);
        }

        // Append DSP nodes (or internal expansion) — nodes only, links deferred
        for (var ad = 0; ad < builtDsp.length; ad++) {
            if (builtDsp[ad].internal) {
                var ie = builtDsp[ad].internal;
                // Convolver nodes
                for (var ic = 0; ic < ie.convNodes.length; ic++) {
                    group.appendChild(ie.convNodes[ic].node.g);
                }
                // Gain nodes
                for (var ig = 0; ig < ie.gainNodes.length; ig++) {
                    group.appendChild(ie.gainNodes[ig].node.g);
                }
            } else if (builtDsp[ad].built) {
                group.appendChild(builtDsp[ad].built.g);
            }
        }

        // Append output nodes
        for (var ao = 0; ao < builtOutputs.length; ao++) {
            group.appendChild(builtOutputs[ao].built.g);
        }

        // Append all links ON TOP of nodes (F-054)
        // Internal links first (conv->gain), then external links
        for (var ad2 = 0; ad2 < builtDsp.length; ad2++) {
            if (builtDsp[ad2].internal) {
                var ie2 = builtDsp[ad2].internal;
                for (var il = 0; il < ie2.internalLinks.length; il++) {
                    group.appendChild(ie2.internalLinks[il]);
                }
            }
        }
        group.appendChild(linksGroup);

        svgEl.appendChild(group);

        // Device status badge on mode label
        var devicesOk = true;
        if (data.devices) {
            for (var dk in data.devices) {
                if (data.devices[dk] !== "present") devicesOk = false;
            }
        }
        if (!devicesOk) {
            modeLabel.setAttribute("fill", PiAudio.cssVar("--danger"));
        }

        fitViewBox();
    }

    // -- Port collection from link data --

    function collectPortNames(links, nodeId, direction) {
        var names = [];
        var seen = {};
        for (var i = 0; i < links.length; i++) {
            var lnk = links[i];
            var name;
            if (direction === "output" && lnk.output_node === nodeId) {
                name = lnk.output_port;
            } else if (direction === "input" && lnk.input_node === nodeId) {
                name = lnk.input_port;
            } else {
                continue;
            }
            if (name && !seen[name]) {
                seen[name] = true;
                names.push(name);
            }
        }
        return names;
    }

    // -- Port resolution for link routing --

    function resolveOutputPort(nodeId, portName, sources, dspList, outputs, internal) {
        // Check if this is a DSP node with internal expansion
        for (var d = 0; d < dspList.length; d++) {
            if (dspList[d].data.id === nodeId && dspList[d].internal) {
                // Route through internal exit ports
                var ie = dspList[d].internal;
                // Find matching exit port by index or name
                for (var xi in ie.exitPorts) {
                    var ep = ie.exitPorts[xi];
                    if (portMatchesIndex(portName, parseInt(xi))) {
                        return ep;
                    }
                }
                // Fallback: try gain node output ports directly
                for (var gi = 0; gi < ie.gainNodes.length; gi++) {
                    var gn = ie.gainNodes[gi];
                    if (portName.indexOf(gn.name.replace("gain_", "")) !== -1 ||
                        portMatchesIndex(portName, gi)) {
                        return gn.node.outputPorts[0];
                    }
                }
                return ie.exitPorts[0] || null;
            }
            if (dspList[d].data.id === nodeId && dspList[d].built) {
                return findPortByName(dspList[d].built.outputPorts, portName);
            }
        }

        // Check sources
        for (var s = 0; s < sources.length; s++) {
            if (sources[s].data.id === nodeId) {
                return findPortByName(sources[s].built.outputPorts, portName);
            }
        }

        // Check outputs (unusual but possible)
        for (var o = 0; o < outputs.length; o++) {
            if (outputs[o].data.id === nodeId) {
                return findPortByName(outputs[o].built.outputPorts, portName);
            }
        }

        return null;
    }

    function resolveInputPort(nodeId, portName, sources, dspList, outputs, internal) {
        // Check DSP nodes with internal expansion
        for (var d = 0; d < dspList.length; d++) {
            if (dspList[d].data.id === nodeId && dspList[d].internal) {
                var ie = dspList[d].internal;
                // Route through internal entry ports
                for (var ei in ie.entryPorts) {
                    var ep = ie.entryPorts[ei];
                    if (portMatchesIndex(portName, parseInt(ei))) {
                        return ep;
                    }
                }
                // Fallback: try convolver node input ports directly
                for (var ci = 0; ci < ie.convNodes.length; ci++) {
                    var cn = ie.convNodes[ci];
                    if (portName.indexOf(cn.name.replace("conv_", "")) !== -1 ||
                        portMatchesIndex(portName, ci)) {
                        return cn.node.inputPorts[0];
                    }
                }
                return ie.entryPorts[0] || null;
            }
            if (dspList[d].data.id === nodeId && dspList[d].built) {
                return findPortByName(dspList[d].built.inputPorts, portName);
            }
        }

        // Check outputs
        for (var o = 0; o < outputs.length; o++) {
            if (outputs[o].data.id === nodeId) {
                return findPortByName(outputs[o].built.inputPorts, portName);
            }
        }

        // Check sources (unusual but possible)
        for (var s = 0; s < sources.length; s++) {
            if (sources[s].data.id === nodeId) {
                return findPortByName(sources[s].built.inputPorts, portName);
            }
        }

        return null;
    }

    function findPortByName(ports, name) {
        if (!ports || ports.length === 0) return null;
        for (var i = 0; i < ports.length; i++) {
            if (ports[i].label === name) return ports[i];
        }
        // Try substring match
        for (var j = 0; j < ports.length; j++) {
            if (name.indexOf(ports[j].label) !== -1 || ports[j].label.indexOf(name) !== -1) {
                return ports[j];
            }
        }
        // Try index extraction from port name (e.g., "input_0" -> index 0)
        var idx = extractPortIndex(name);
        if (idx !== null && idx < ports.length) {
            return ports[idx];
        }
        return null;
    }

    function portMatchesIndex(portName, idx) {
        var portIdx = extractPortIndex(portName);
        return portIdx === idx;
    }

    function extractPortIndex(name) {
        var m = name.match(/(\d+)$/);
        if (m) return parseInt(m[1], 10);
        // AUX0..AUX3 style
        m = name.match(/AUX(\d+)/i);
        if (m) return parseInt(m[1], 10);
        return null;
    }

    // -- ViewBox fitting + pan/zoom (F-085 #7) --

    function applyViewBox() {
        if (!svgEl) return;
        svgEl.setAttribute("viewBox",
            curVB.x + " " + curVB.y + " " + curVB.w + " " + curVB.h);
    }

    function fitViewBox() {
        if (!svgEl) return;
        try {
            var bbox = svgEl.getBBox();
            if (bbox.width > 0 && bbox.height > 0) {
                var pad = 16;
                curVB.x = Math.max(0, bbox.x - pad);
                curVB.y = Math.max(0, bbox.y - pad);
                curVB.w = bbox.width + pad * 2;
                curVB.h = bbox.height + pad * 2;
                fitVB.w = curVB.w;
                fitVB.h = curVB.h;
                applyViewBox();
            }
        } catch (e) {
            // getBBox fails if SVG not visible
        }
    }

    function svgPointFromEvent(evt) {
        var rect = svgEl.getBoundingClientRect();
        var sx = (evt.clientX - rect.left) / rect.width;
        var sy = (evt.clientY - rect.top) / rect.height;
        return { x: curVB.x + sx * curVB.w, y: curVB.y + sy * curVB.h };
    }

    function clampZoom(newW, newH) {
        // Clamp zoom range relative to fitted content size
        if (newW < fitVB.w * ZOOM_MIN || newH < fitVB.h * ZOOM_MIN) return false;
        if (newW > fitVB.w * ZOOM_MAX || newH > fitVB.h * ZOOM_MAX) return false;
        return true;
    }

    function onWheel(evt) {
        evt.preventDefault();
        var factor = evt.deltaY > 0 ? 1.15 : 1 / 1.15;
        var newW = curVB.w * factor;
        var newH = curVB.h * factor;
        if (!clampZoom(newW, newH)) return;
        var pt = svgPointFromEvent(evt);
        curVB.x = pt.x - (pt.x - curVB.x) * factor;
        curVB.y = pt.y - (pt.y - curVB.y) * factor;
        curVB.w = newW;
        curVB.h = newH;
        applyViewBox();
    }

    function onPanStart(evt) {
        if (evt.button !== 0) return;
        isPanning = true;
        panStartX = evt.clientX;
        panStartY = evt.clientY;
        svgEl.style.cursor = "grabbing";
        evt.preventDefault();
    }

    function onPanMove(evt) {
        if (!isPanning) return;
        var rect = svgEl.getBoundingClientRect();
        var dx = (evt.clientX - panStartX) / rect.width * curVB.w;
        var dy = (evt.clientY - panStartY) / rect.height * curVB.h;
        curVB.x -= dx;
        curVB.y -= dy;
        panStartX = evt.clientX;
        panStartY = evt.clientY;
        applyViewBox();
    }

    function onPanEnd() {
        if (!isPanning) return;
        isPanning = false;
        svgEl.style.cursor = "grab";
    }

    function onDblClick() {
        fitViewBox();
    }

    // -- Touch handlers for pinch-to-zoom + drag-to-pan --

    function touchDist(t1, t2) {
        var dx = t1.clientX - t2.clientX;
        var dy = t1.clientY - t2.clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }

    function touchMidSVG(t1, t2) {
        var rect = svgEl.getBoundingClientRect();
        var mx = ((t1.clientX + t2.clientX) / 2 - rect.left) / rect.width;
        var my = ((t1.clientY + t2.clientY) / 2 - rect.top) / rect.height;
        return { x: curVB.x + mx * curVB.w, y: curVB.y + my * curVB.h };
    }

    function onTouchStart(evt) {
        if (evt.touches.length === 2) {
            evt.preventDefault();
            lastTouchDist = touchDist(evt.touches[0], evt.touches[1]);
            lastTouchMid = touchMidSVG(evt.touches[0], evt.touches[1]);
        } else if (evt.touches.length === 1) {
            isPanning = true;
            panStartX = evt.touches[0].clientX;
            panStartY = evt.touches[0].clientY;
        }
    }

    function onTouchMove(evt) {
        if (evt.touches.length === 2) {
            evt.preventDefault();
            var dist = touchDist(evt.touches[0], evt.touches[1]);
            if (lastTouchDist > 0) {
                var factor = lastTouchDist / dist;
                var newW = curVB.w * factor;
                var newH = curVB.h * factor;
                if (clampZoom(newW, newH)) {
                    var mid = touchMidSVG(evt.touches[0], evt.touches[1]);
                    curVB.x = mid.x - (mid.x - curVB.x) * factor;
                    curVB.y = mid.y - (mid.y - curVB.y) * factor;
                    curVB.w = newW;
                    curVB.h = newH;
                    applyViewBox();
                }
            }
            lastTouchDist = dist;
            lastTouchMid = touchMidSVG(evt.touches[0], evt.touches[1]);
        } else if (evt.touches.length === 1 && isPanning) {
            var rect = svgEl.getBoundingClientRect();
            var dx = (evt.touches[0].clientX - panStartX) / rect.width * curVB.w;
            var dy = (evt.touches[0].clientY - panStartY) / rect.height * curVB.h;
            curVB.x -= dx;
            curVB.y -= dy;
            panStartX = evt.touches[0].clientX;
            panStartY = evt.touches[0].clientY;
            applyViewBox();
        }
    }

    function onTouchEnd(evt) {
        if (evt.touches.length < 2) {
            lastTouchDist = 0;
        }
        if (evt.touches.length === 0) {
            isPanning = false;
        }
    }

    function initPanZoom() {
        if (!svgEl) return;
        svgEl.style.cursor = "grab";
        // Mouse events
        svgEl.addEventListener("wheel", onWheel, { passive: false });
        svgEl.addEventListener("mousedown", onPanStart);
        window.addEventListener("mousemove", onPanMove);
        window.addEventListener("mouseup", onPanEnd);
        svgEl.addEventListener("dblclick", onDblClick);
        // Touch events (pinch zoom + drag pan)
        svgEl.addEventListener("touchstart", onTouchStart, { passive: false });
        svgEl.addEventListener("touchmove", onTouchMove, { passive: false });
        svgEl.addEventListener("touchend", onTouchEnd);
        // Fit button
        var fitBtn = document.getElementById("gv-fit-btn");
        if (fitBtn) fitBtn.addEventListener("click", fitViewBox);
    }

    // -- Topology polling --

    function fetchTopology() {
        var url = "/api/v1/graph/topology";
        fetch(url)
            .then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.json();
            })
            .then(function (data) {
                var json = JSON.stringify(data);
                if (json !== lastTopologyJSON) {
                    lastTopologyJSON = json;
                    renderTopology(data);
                }
            })
            .catch(function (err) {
                // Silently retry on next poll
            });
    }

    function startPolling() {
        if (pollTimer) return;
        fetchTopology();
        pollTimer = setInterval(fetchTopology, POLL_INTERVAL_MS);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    // -- View lifecycle --

    function init() {
        initNodeColors();
        svgEl = document.getElementById("gv-svg");
        if (!svgEl) return;
        svgEl.appendChild(buildDefs());
        initPanZoom();
    }

    function onShow() {
        startPolling();
    }

    function onHide() {
        stopPolling();
    }

    // -- Register view --

    PiAudio.registerView("graph", {
        init: init,
        onShow: onShow,
        onHide: onHide
    });

})();
