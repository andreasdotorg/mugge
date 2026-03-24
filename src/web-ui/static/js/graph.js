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
            source: cv("--group-app"),
            dsp:    cv("--group-gain"),
            gain:   cv("--group-gain"),
            output: cv("--group-hw"),
            other:  cv("--group-main")
        };
    }

    // -- State --

    var svgEl = null;
    var pollTimer = null;
    var lastTopologyJSON = null;
    var POLL_INTERVAL_MS = 2000;

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

        // Title
        g.appendChild(svgText(w / 2, HEADER_H / 2, opts.label, "gv-node-label"));

        // Sublabel (description)
        if (opts.sublabel) {
            g.appendChild(svgText(w / 2, HEADER_H + 14, opts.sublabel, "gv-node-sublabel"));
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
                g.appendChild(svgText(14, py, opts.inputs[i], "gv-port-label gv-port-label--input"));
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
                g.appendChild(svgText(w - 14, py2, opts.outputs[j], "gv-port-label gv-port-label--output"));
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

    function classifyNode(node) {
        var mc = (node.media_class || "").toLowerCase();
        if (mc.indexOf("stream/output") !== -1) return "source";
        if (mc.indexOf("stream/input") !== -1) return "source";
        if (mc === "audio/sink" && node.name === "pi4audio-convolver") return "dsp";
        if (mc === "audio/sink") return "output";
        if (mc === "audio/source") return "output";
        // Fallback: skip GraphManager-like nodes that don't produce audio
        if (node.name && node.name.indexOf("graphmanager") !== -1) return "skip";
        return "other";
    }

    function colorKeyForClass(cls) {
        if (cls === "source") return "source";
        if (cls === "dsp") return "dsp";
        if (cls === "output") return "output";
        return "other";
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

        // Classify nodes into columns
        var sources = [];
        var dspNodes = [];
        var outputs = [];
        var nodeMap = {};  // id -> node data

        for (var n = 0; n < data.nodes.length; n++) {
            var node = data.nodes[n];
            nodeMap[node.id] = node;
            var cls = classifyNode(node);
            if (cls === "source") sources.push(node);
            else if (cls === "dsp") dspNodes.push(node);
            else if (cls === "output") outputs.push(node);
            // skip "skip" and "other" nodes
        }

        // If no DSP nodes found but we have a convolver in nodes, it should be DSP
        // (this handles edge cases where media_class might differ)

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

        var centerY = SVG_H / 2;

        // Build source nodes
        var builtSources = [];
        var srcTotalH = 0;
        for (var s = 0; s < sources.length; s++) {
            var src = sources[s];
            var srcOuts = collectPortNames(data.links, src.id, "output");
            if (srcOuts.length === 0) srcOuts = ["out_0", "out_1"];
            var srcH = HEADER_H + PORT_PAD + Math.max(1, srcOuts.length) * PORT_ROW_H + PORT_PAD;
            srcTotalH += srcH + (s > 0 ? NODE_GAP : 0);
        }
        var srcY = centerY - srcTotalH / 2;
        for (var s2 = 0; s2 < sources.length; s2++) {
            var src2 = sources[s2];
            var srcOuts2 = collectPortNames(data.links, src2.id, "output");
            if (srcOuts2.length === 0) srcOuts2 = ["out_0", "out_1"];
            var built = buildNode({
                id: "gv-node-" + src2.id,
                label: src2.description || src2.name,
                colorKey: "source",
                x: colX[0], y: srcY,
                inputs: [],
                outputs: srcOuts2,
                state: src2.state === "running" ? "active" : "absent",
                gm_managed: src2.gm_managed
            });
            builtSources.push({ data: src2, built: built });
            srcY += built.height + NODE_GAP;
        }

        // Build output nodes
        var builtOutputs = [];
        var outTotalH = 0;
        for (var o = 0; o < outputs.length; o++) {
            var out = outputs[o];
            var outIns = collectPortNames(data.links, out.id, "input");
            if (outIns.length === 0) outIns = ["in_0", "in_1"];
            var outH = HEADER_H + PORT_PAD + Math.max(1, outIns.length) * PORT_ROW_H + PORT_PAD;
            outTotalH += outH + (o > 0 ? NODE_GAP : 0);
        }
        var outY = centerY - outTotalH / 2;
        var outColIdx = hasInternal ? 3 : 2;
        for (var o2 = 0; o2 < outputs.length; o2++) {
            var out2 = outputs[o2];
            var outIns2 = collectPortNames(data.links, out2.id, "input");
            if (outIns2.length === 0) outIns2 = ["in_0", "in_1"];
            var builtOut = buildNode({
                id: "gv-node-" + out2.id,
                label: out2.description || out2.name,
                colorKey: "output",
                x: colX[outColIdx], y: outY,
                inputs: outIns2,
                outputs: [],
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

        // Append in SVG painter's order: links, then nodes
        group.appendChild(linksGroup);

        // Append source nodes
        for (var as = 0; as < builtSources.length; as++) {
            group.appendChild(builtSources[as].built.g);
        }

        // Append DSP nodes (or internal expansion)
        for (var ad = 0; ad < builtDsp.length; ad++) {
            if (builtDsp[ad].internal) {
                var ie = builtDsp[ad].internal;
                // Internal links
                for (var il = 0; il < ie.internalLinks.length; il++) {
                    group.appendChild(ie.internalLinks[il]);
                }
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

    // -- ViewBox fitting --

    function fitViewBox() {
        if (!svgEl) return;
        try {
            var bbox = svgEl.getBBox();
            if (bbox.width > 0 && bbox.height > 0) {
                var pad = 16;
                var vbX = Math.max(0, bbox.x - pad);
                var vbY = Math.max(0, bbox.y - pad);
                var vbW = bbox.width + pad * 2;
                var vbH = bbox.height + pad * 2;
                svgEl.setAttribute("viewBox", vbX + " " + vbY + " " + vbW + " " + vbH);
            }
        } catch (e) {
            // getBBox fails if SVG not visible
        }
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
