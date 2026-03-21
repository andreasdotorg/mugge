/**
 * D-020 Web UI — Graph view module (US-064).
 *
 * Renders PipeWire node topology as static SVG diagrams.
 * Four templates (DJ, Live, Monitoring, Measurement) match the
 * GraphManager routing table modes. Real-time data from /ws/system
 * selects the active template and updates node/link state indicators.
 *
 * Three-column left-to-right signal flow:
 *   Sources (col 1) -> DSP (col 2) -> Outputs (col 3)
 *
 * No external dependencies. Pure SVG + CSS transitions.
 */

"use strict";

(function () {

    // -- Layout constants (match UX spec) --

    var SVG_W = 860;
    var SVG_H = 480;
    var COL_X = [80, 360, 640];    // column center x
    var NODE_W = 160;
    var NODE_W_COMPOUND = 180;
    var HEADER_H = 24;
    var PORT_ROW_H = 22;
    var PORT_PAD = 8;
    var PORT_R = 6;
    var NODE_R = 6;
    var NODE_GAP = 24;

    var NS = "http://www.w3.org/2000/svg";

    // -- Node type colors (from UX spec / dashboard GROUP_COLORS) --

    var NODE_COLORS = {
        app:  "#00838f",
        dsp:  "#2e7d32",
        hw:   "#c17900",
        main: "#8a94a4"
    };

    // -- State --

    var currentMode = null;
    var svgEl = null;

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

        // Standard arrowhead (grey)
        var m1 = svgCreate("marker", {
            id: "gv-arrow", markerWidth: "8", markerHeight: "6",
            refX: "8", refY: "3", orient: "auto", markerUnits: "userSpaceOnUse"
        });
        var p1 = svgCreate("path", { d: "M0,0 L8,3 L0,6 Z", "class": "gv-arrowhead" });
        m1.appendChild(p1);
        defs.appendChild(m1);

        // Blue arrowhead (bypass)
        var m2 = svgCreate("marker", {
            id: "gv-arrow-blue", markerWidth: "8", markerHeight: "6",
            refX: "8", refY: "3", orient: "auto", markerUnits: "userSpaceOnUse"
        });
        var p2 = svgCreate("path", { d: "M0,0 L8,3 L0,6 Z", "class": "gv-arrowhead-blue" });
        m2.appendChild(p2);
        defs.appendChild(m2);

        // Red arrowhead (failed)
        var m3 = svgCreate("marker", {
            id: "gv-arrow-red", markerWidth: "8", markerHeight: "6",
            refX: "8", refY: "3", orient: "auto", markerUnits: "userSpaceOnUse"
        });
        var p3 = svgCreate("path", { d: "M0,0 L8,3 L0,6 Z", "class": "gv-arrowhead-red" });
        m3.appendChild(p3);
        defs.appendChild(m3);

        return defs;
    }

    // -- Node builder --

    /**
     * Build an SVG node group.
     * @param {object} opts
     * @param {string} opts.id       - Element ID (e.g., "gv-node-mixxx")
     * @param {string} opts.label    - Display name
     * @param {string} opts.color    - Header bar color key (app/dsp/hw/main)
     * @param {number} opts.x        - Center x
     * @param {number} opts.y        - Top y
     * @param {string[]} opts.inputs - Input port labels (left edge)
     * @param {string[]} opts.outputs- Output port labels (right edge)
     * @param {boolean} opts.compound- Use wider compound width
     * @param {string} opts.state    - "active", "absent", "error", "ghost"
     * @param {string} opts.ghostText- Text for ghost node
     * @returns {{g: SVGElement, inputPorts: {label:string, cx:number, cy:number}[], outputPorts: {label:string, cx:number, cy:number}[], width:number, height:number}}
     */
    function buildNode(opts) {
        var w = opts.compound ? NODE_W_COMPOUND : NODE_W;
        var maxPorts = Math.max(opts.inputs ? opts.inputs.length : 0, opts.outputs ? opts.outputs.length : 0);
        var portAreaH = maxPorts > 0 ? PORT_PAD + maxPorts * PORT_ROW_H + PORT_PAD : 40;
        var h = HEADER_H + portAreaH;
        var x = opts.x - w / 2;
        var y = opts.y;

        var stateClass = "gv-node--" + (opts.state || "active");
        var g = svgCreate("g", {
            id: opts.id,
            "class": "gv-node " + stateClass,
            transform: "translate(" + x + "," + y + ")"
        });

        // Main rect
        g.appendChild(svgCreate("rect", {
            "class": "gv-node-rect",
            x: 0, y: 0, width: w, height: h, rx: NODE_R, ry: NODE_R
        }));

        if (opts.state !== "ghost") {
            // Header bar (clipped to top corners only via a mask rect)
            var color = NODE_COLORS[opts.color] || NODE_COLORS.main;
            g.appendChild(svgCreate("rect", {
                "class": "gv-node-header",
                x: 0, y: 0, width: w, height: HEADER_H,
                rx: NODE_R, ry: NODE_R,
                fill: color
            }));
            // Mask bottom corners of header to be square
            g.appendChild(svgCreate("rect", {
                "class": "gv-node-header-mask",
                x: 0, y: HEADER_H - NODE_R, width: w, height: NODE_R
            }));

            // Title
            g.appendChild(svgText(w / 2, HEADER_H / 2, opts.label, "gv-node-label"));
        } else {
            // Ghost node — centered text
            g.appendChild(svgText(w / 2, h / 2, opts.ghostText || "No source linked", "gv-node-label"));
        }

        // Ports
        var inputPorts = [];
        var outputPorts = [];
        var portStartY = HEADER_H + PORT_PAD;

        if (opts.inputs && opts.inputs.length > 0) {
            // If fewer inputs than outputs, center inputs vertically
            var inOffset = 0;
            if (opts.outputs && opts.inputs.length < opts.outputs.length) {
                inOffset = (opts.outputs.length - opts.inputs.length) * PORT_ROW_H / 2;
            }
            for (var i = 0; i < opts.inputs.length; i++) {
                var py = portStartY + inOffset + i * PORT_ROW_H + PORT_ROW_H / 2;
                var cx = 0;
                var cy = py;
                g.appendChild(svgCreate("circle", {
                    "class": "gv-port gv-port--input gv-port--idle",
                    cx: cx, cy: cy, r: PORT_R,
                    "data-port": opts.inputs[i]
                }));
                g.appendChild(svgText(14, cy, opts.inputs[i], "gv-port-label gv-port-label--input"));
                inputPorts.push({ label: opts.inputs[i], cx: x + cx, cy: y + cy });
            }
        }

        if (opts.outputs && opts.outputs.length > 0) {
            var outOffset = 0;
            if (opts.inputs && opts.outputs.length < opts.inputs.length) {
                outOffset = (opts.inputs.length - opts.outputs.length) * PORT_ROW_H / 2;
            }
            for (var j = 0; j < opts.outputs.length; j++) {
                var py2 = portStartY + outOffset + j * PORT_ROW_H + PORT_ROW_H / 2;
                var cx2 = w;
                var cy2 = py2;
                g.appendChild(svgCreate("circle", {
                    "class": "gv-port gv-port--output gv-port--idle",
                    cx: cx2, cy: cy2, r: PORT_R,
                    "data-port": opts.outputs[j]
                }));
                g.appendChild(svgText(w - 14, cy2, opts.outputs[j], "gv-port-label gv-port-label--output"));
                outputPorts.push({ label: opts.outputs[j], cx: x + cx2, cy: y + cy2 });
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

    function buildBypassArc(x1, y1, x2, y2, yOffset) {
        var midX = (x1 + x2) / 2;
        var midY = (y1 + y2) / 2 + yOffset;
        var d = "M " + x1 + " " + y1 +
                " Q " + midX + " " + midY + " " + x2 + " " + y2;
        return svgCreate("path", {
            d: d,
            "class": "gv-bypass-arc",
            "marker-end": "url(#gv-arrow-blue)"
        });
    }

    function buildYJunction(x, y) {
        return svgCreate("circle", {
            "class": "gv-yjunction",
            cx: x, cy: y, r: 5
        });
    }

    // -- Helper: vertically center a stack of nodes --

    function stackNodes(nodes) {
        var totalH = 0;
        for (var i = 0; i < nodes.length; i++) {
            totalH += nodes[i].height;
            if (i > 0) totalH += NODE_GAP;
        }
        var startY = (SVG_H - totalH) / 2;
        var y = startY;
        for (var j = 0; j < nodes.length; j++) {
            nodes[j].y = y;
            y += nodes[j].height + NODE_GAP;
        }
    }

    // -- Template: Monitoring --

    function buildMonitoringTemplate() {
        var group = svgCreate("g", { "class": "gv-template-group" });

        // Calculate node heights first for centering
        var ghostH = HEADER_H + PORT_PAD + 0 + PORT_PAD + 16; // minimal ghost
        ghostH = 72; // fixed ghost height
        var convMaxPorts = 4;
        var convH = HEADER_H + PORT_PAD + convMaxPorts * PORT_ROW_H + PORT_PAD;
        var usbPorts = 8;
        var usbH = HEADER_H + PORT_PAD + usbPorts * PORT_ROW_H + PORT_PAD;

        // Vertical centering
        var heights = [
            { height: ghostH },
            { height: convH },
            { height: usbH }
        ];
        stackNodes(heights);

        // Ghost node (col 1)
        var ghost = buildNode({
            id: "gv-node-ghost", label: "No source linked", color: "main",
            x: COL_X[0], y: heights[0].y,
            inputs: [], outputs: [],
            state: "ghost", ghostText: "No source linked"
        });
        group.appendChild(ghost.g);

        // Convolver (col 2)
        var conv = buildNode({
            id: "gv-node-convolver", label: "Convolver", color: "dsp",
            x: COL_X[1], y: heights[1].y,
            inputs: ["AUX0", "AUX1", "AUX2", "AUX3"],
            outputs: ["out0", "out1", "out2", "out3"],
            state: "active"
        });
        group.appendChild(conv.g);

        // USBStreamer (col 3)
        var usb = buildNode({
            id: "gv-node-usbstreamer", label: "USBStreamer", color: "hw",
            x: COL_X[2], y: heights[2].y,
            inputs: ["ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7", "ch8"],
            outputs: [],
            state: "active"
        });
        group.appendChild(usb.g);

        // Links: convolver out0-3 -> USBStreamer ch1-4
        for (var i = 0; i < 4; i++) {
            var link = buildLink(
                conv.outputPorts[i].cx, conv.outputPorts[i].cy,
                usb.inputPorts[i].cx, usb.inputPorts[i].cy,
                "gv-link--connected", "gv-arrow"
            );
            // Insert links before nodes for z-order
            group.insertBefore(link, ghost.g);
        }

        return group;
    }

    // -- Template: DJ --

    function buildDjTemplate() {
        var group = svgCreate("g", { "class": "gv-template-group" });

        // Node heights
        var mixxxOuts = ["L", "R", "HP L", "HP R"];
        var convIns = ["AUX0", "AUX1", "AUX2", "AUX3"];
        var convOuts = ["out0", "out1", "out2", "out3"];
        var usbIns = ["ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7", "ch8"];

        var mixxxH = HEADER_H + PORT_PAD + mixxxOuts.length * PORT_ROW_H + PORT_PAD;
        var convH = HEADER_H + PORT_PAD + Math.max(convIns.length, convOuts.length) * PORT_ROW_H + PORT_PAD;
        var usbH = HEADER_H + PORT_PAD + usbIns.length * PORT_ROW_H + PORT_PAD;

        // Center all three columns vertically based on tallest
        var maxH = Math.max(mixxxH, convH, usbH);
        var mixxxY = (SVG_H - mixxxH) / 2;
        var convY = (SVG_H - convH) / 2;
        var usbY = (SVG_H - usbH) / 2;

        // Mixxx (col 1)
        var mixxx = buildNode({
            id: "gv-node-mixxx", label: "Mixxx", color: "app",
            x: COL_X[0], y: mixxxY,
            inputs: [], outputs: mixxxOuts,
            state: "active"
        });
        group.appendChild(mixxx.g);

        // Convolver (col 2)
        var conv = buildNode({
            id: "gv-node-convolver", label: "Convolver", color: "dsp",
            x: COL_X[1], y: convY,
            inputs: convIns, outputs: convOuts,
            state: "active"
        });
        group.appendChild(conv.g);

        // USBStreamer (col 3)
        var usb = buildNode({
            id: "gv-node-usbstreamer", label: "USBStreamer", color: "hw",
            x: COL_X[2], y: usbY,
            inputs: usbIns, outputs: [],
            state: "active"
        });
        group.appendChild(usb.g);

        // Links layer (inserted before nodes for z-order)
        var linksGroup = svgCreate("g");

        // Mixxx L -> Convolver AUX0 (left main)
        linksGroup.appendChild(buildLink(
            mixxx.outputPorts[0].cx, mixxx.outputPorts[0].cy,
            conv.inputPorts[0].cx, conv.inputPorts[0].cy,
            "gv-link--connected", "gv-arrow"
        ));

        // Mixxx R -> Convolver AUX1 (right main)
        linksGroup.appendChild(buildLink(
            mixxx.outputPorts[1].cx, mixxx.outputPorts[1].cy,
            conv.inputPorts[1].cx, conv.inputPorts[1].cy,
            "gv-link--connected", "gv-arrow"
        ));

        // Y-junction: Mixxx L+R -> Convolver AUX2 (sub1)
        var jx1 = (COL_X[0] + NODE_W / 2 + COL_X[1] - NODE_W / 2) / 2;
        var jy1 = conv.inputPorts[2].cy;
        linksGroup.appendChild(buildLink(
            mixxx.outputPorts[0].cx, mixxx.outputPorts[0].cy,
            jx1, jy1, "gv-link--connected", null
        ));
        linksGroup.appendChild(buildLink(
            mixxx.outputPorts[1].cx, mixxx.outputPorts[1].cy,
            jx1, jy1, "gv-link--connected", null
        ));
        linksGroup.appendChild(buildYJunction(jx1, jy1));
        linksGroup.appendChild(buildLink(
            jx1, jy1,
            conv.inputPorts[2].cx, conv.inputPorts[2].cy,
            "gv-link--connected", "gv-arrow"
        ));

        // Y-junction: Mixxx L+R -> Convolver AUX3 (sub2)
        var jy2 = conv.inputPorts[3].cy;
        linksGroup.appendChild(buildLink(
            mixxx.outputPorts[0].cx, mixxx.outputPorts[0].cy,
            jx1, jy2, "gv-link--connected", null
        ));
        linksGroup.appendChild(buildLink(
            mixxx.outputPorts[1].cx, mixxx.outputPorts[1].cy,
            jx1, jy2, "gv-link--connected", null
        ));
        linksGroup.appendChild(buildYJunction(jx1, jy2));
        linksGroup.appendChild(buildLink(
            jx1, jy2,
            conv.inputPorts[3].cx, conv.inputPorts[3].cy,
            "gv-link--connected", "gv-arrow"
        ));

        // Convolver -> USBStreamer ch1-4
        for (var i = 0; i < 4; i++) {
            linksGroup.appendChild(buildLink(
                conv.outputPorts[i].cx, conv.outputPorts[i].cy,
                usb.inputPorts[i].cx, usb.inputPorts[i].cy,
                "gv-link--connected", "gv-arrow"
            ));
        }

        // Bypass: Mixxx HP L -> USBStreamer ch5 (arc above)
        linksGroup.appendChild(buildBypassArc(
            mixxx.outputPorts[2].cx, mixxx.outputPorts[2].cy,
            usb.inputPorts[4].cx, usb.inputPorts[4].cy,
            -40
        ));

        // Bypass: Mixxx HP R -> USBStreamer ch6 (arc above)
        linksGroup.appendChild(buildBypassArc(
            mixxx.outputPorts[3].cx, mixxx.outputPorts[3].cy,
            usb.inputPorts[5].cx, usb.inputPorts[5].cy,
            -40
        ));

        group.insertBefore(linksGroup, mixxx.g);

        return group;
    }

    // -- Template: Live --

    function buildLiveTemplate() {
        var group = svgCreate("g", { "class": "gv-template-group" });

        // ADA8200 in col 1 (capture input device)
        var adaOuts = ["ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7", "ch8"];

        // Reaper in col 1 (compound: 8 in + 6 out)
        var reaperIns = ["in1", "in2", "in3", "in4", "in5", "in6", "in7", "in8"];
        var reaperOuts = ["out1", "out2", "HP L", "HP R", "IEM L", "IEM R"];

        var convIns = ["AUX0", "AUX1", "AUX2", "AUX3"];
        var convOuts = ["out0", "out1", "out2", "out3"];
        var usbIns = ["ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7", "ch8"];

        // Heights
        var adaH = HEADER_H + PORT_PAD + adaOuts.length * PORT_ROW_H + PORT_PAD;
        var reaperH = HEADER_H + PORT_PAD + Math.max(reaperIns.length, reaperOuts.length) * PORT_ROW_H + PORT_PAD;
        var convH = HEADER_H + PORT_PAD + convIns.length * PORT_ROW_H + PORT_PAD;
        var usbH = HEADER_H + PORT_PAD + usbIns.length * PORT_ROW_H + PORT_PAD;

        // Position: ADA8200 and Reaper share col 1 (ADA above, Reaper below)
        // Actually, ADA8200 outputs feed Reaper inputs — they should be
        // separate columns or ADA8200 to the far left. Let's put ADA8200
        // at x=40, Reaper at x=180, Convolver at x=400, USBStreamer at x=660
        // to fit the extra column.
        var adaX = 50;
        var reaperX = 240;
        var convX = 440;
        var usbX = 680;

        var centerY = SVG_H / 2;

        // Vertical centering per column
        var adaY = centerY - adaH / 2;
        var reaperY = centerY - reaperH / 2;
        var convY = centerY - convH / 2;
        var usbY = centerY - usbH / 2;

        // ADA8200 (far left)
        var ada = buildNode({
            id: "gv-node-ada8200", label: "ADA8200", color: "hw",
            x: adaX, y: adaY,
            inputs: [], outputs: adaOuts,
            state: "active"
        });
        group.appendChild(ada.g);

        // Reaper (compound, col 1.5)
        var reaper = buildNode({
            id: "gv-node-reaper", label: "Reaper", color: "app",
            x: reaperX, y: reaperY,
            inputs: reaperIns, outputs: reaperOuts,
            compound: true, state: "active"
        });
        group.appendChild(reaper.g);

        // Convolver (col 2)
        var conv = buildNode({
            id: "gv-node-convolver", label: "Convolver", color: "dsp",
            x: convX, y: convY,
            inputs: convIns, outputs: convOuts,
            state: "active"
        });
        group.appendChild(conv.g);

        // USBStreamer (col 3)
        var usb = buildNode({
            id: "gv-node-usbstreamer", label: "USBStreamer", color: "hw",
            x: usbX, y: usbY,
            inputs: usbIns, outputs: [],
            state: "active"
        });
        group.appendChild(usb.g);

        // Links
        var linksGroup = svgCreate("g");

        // ADA8200 ch1-8 -> Reaper in1-8
        for (var i = 0; i < 8; i++) {
            linksGroup.appendChild(buildLink(
                ada.outputPorts[i].cx, ada.outputPorts[i].cy,
                reaper.inputPorts[i].cx, reaper.inputPorts[i].cy,
                "gv-link--connected", "gv-arrow"
            ));
        }

        // Reaper out1 -> Convolver AUX0 (left main)
        linksGroup.appendChild(buildLink(
            reaper.outputPorts[0].cx, reaper.outputPorts[0].cy,
            conv.inputPorts[0].cx, conv.inputPorts[0].cy,
            "gv-link--connected", "gv-arrow"
        ));

        // Reaper out2 -> Convolver AUX1 (right main)
        linksGroup.appendChild(buildLink(
            reaper.outputPorts[1].cx, reaper.outputPorts[1].cy,
            conv.inputPorts[1].cx, conv.inputPorts[1].cy,
            "gv-link--connected", "gv-arrow"
        ));

        // Y-junction: Reaper out1+out2 -> Convolver AUX2 (sub1)
        var jx = (reaperX + NODE_W_COMPOUND / 2 + convX - NODE_W / 2) / 2;
        var jy1 = conv.inputPorts[2].cy;
        linksGroup.appendChild(buildLink(
            reaper.outputPorts[0].cx, reaper.outputPorts[0].cy,
            jx, jy1, "gv-link--connected", null
        ));
        linksGroup.appendChild(buildLink(
            reaper.outputPorts[1].cx, reaper.outputPorts[1].cy,
            jx, jy1, "gv-link--connected", null
        ));
        linksGroup.appendChild(buildYJunction(jx, jy1));
        linksGroup.appendChild(buildLink(
            jx, jy1,
            conv.inputPorts[2].cx, conv.inputPorts[2].cy,
            "gv-link--connected", "gv-arrow"
        ));

        // Y-junction: Reaper out1+out2 -> Convolver AUX3 (sub2)
        var jy2 = conv.inputPorts[3].cy;
        linksGroup.appendChild(buildLink(
            reaper.outputPorts[0].cx, reaper.outputPorts[0].cy,
            jx, jy2, "gv-link--connected", null
        ));
        linksGroup.appendChild(buildLink(
            reaper.outputPorts[1].cx, reaper.outputPorts[1].cy,
            jx, jy2, "gv-link--connected", null
        ));
        linksGroup.appendChild(buildYJunction(jx, jy2));
        linksGroup.appendChild(buildLink(
            jx, jy2,
            conv.inputPorts[3].cx, conv.inputPorts[3].cy,
            "gv-link--connected", "gv-arrow"
        ));

        // Convolver -> USBStreamer ch1-4
        for (var c = 0; c < 4; c++) {
            linksGroup.appendChild(buildLink(
                conv.outputPorts[c].cx, conv.outputPorts[c].cy,
                usb.inputPorts[c].cx, usb.inputPorts[c].cy,
                "gv-link--connected", "gv-arrow"
            ));
        }

        // Bypass: Reaper HP L -> USBStreamer ch5 (arc above)
        linksGroup.appendChild(buildBypassArc(
            reaper.outputPorts[2].cx, reaper.outputPorts[2].cy,
            usb.inputPorts[4].cx, usb.inputPorts[4].cy,
            -40
        ));

        // Bypass: Reaper HP R -> USBStreamer ch6 (arc above)
        linksGroup.appendChild(buildBypassArc(
            reaper.outputPorts[3].cx, reaper.outputPorts[3].cy,
            usb.inputPorts[5].cx, usb.inputPorts[5].cy,
            -40
        ));

        // Bypass: Reaper IEM L -> USBStreamer ch7 (arc below)
        linksGroup.appendChild(buildBypassArc(
            reaper.outputPorts[4].cx, reaper.outputPorts[4].cy,
            usb.inputPorts[6].cx, usb.inputPorts[6].cy,
            40
        ));

        // Bypass: Reaper IEM R -> USBStreamer ch8 (arc below)
        linksGroup.appendChild(buildBypassArc(
            reaper.outputPorts[5].cx, reaper.outputPorts[5].cy,
            usb.inputPorts[7].cx, usb.inputPorts[7].cy,
            40
        ));

        group.insertBefore(linksGroup, ada.g);

        return group;
    }

    // -- Template: Measurement --

    function buildMeasurementTemplate() {
        var group = svgCreate("g", { "class": "gv-template-group" });

        // UMIK-1 (col 0, far left)
        // Signal-gen (col 1, compound: 1 in + 4 out)
        // Convolver (col 2)
        // USBStreamer (col 3)

        var umikX = 50;
        var siggenX = 220;
        var convX = 440;
        var usbX = 680;

        var siggenIns = ["mic"];
        var siggenOuts = ["ch0", "ch1", "ch2", "ch3"];
        var convIns = ["AUX0", "AUX1", "AUX2", "AUX3"];
        var convOuts = ["out0", "out1", "out2", "out3"];
        var usbIns = ["ch1", "ch2", "ch3", "ch4"];

        // Heights
        var umikH = HEADER_H + PORT_PAD + 1 * PORT_ROW_H + PORT_PAD;
        var siggenH = HEADER_H + PORT_PAD + Math.max(siggenIns.length, siggenOuts.length) * PORT_ROW_H + PORT_PAD;
        var convH = HEADER_H + PORT_PAD + convIns.length * PORT_ROW_H + PORT_PAD;
        var usbH = HEADER_H + PORT_PAD + usbIns.length * PORT_ROW_H + PORT_PAD;

        var centerY = SVG_H / 2;

        var umikY = centerY - umikH / 2;
        var siggenY = centerY - siggenH / 2;
        var convY = centerY - convH / 2;
        var usbY = centerY - usbH / 2;

        // UMIK-1 (absent by default until device detected)
        var umik = buildNode({
            id: "gv-node-umik1", label: "UMIK-1", color: "hw",
            x: umikX, y: umikY,
            inputs: [], outputs: ["capture"],
            state: "absent"
        });
        group.appendChild(umik.g);

        // Signal-gen (compound)
        var siggen = buildNode({
            id: "gv-node-siggen", label: "Signal Gen", color: "app",
            x: siggenX, y: siggenY,
            inputs: siggenIns, outputs: siggenOuts,
            compound: true, state: "active"
        });
        group.appendChild(siggen.g);

        // Convolver
        var conv = buildNode({
            id: "gv-node-convolver", label: "Convolver", color: "dsp",
            x: convX, y: convY,
            inputs: convIns, outputs: convOuts,
            state: "active"
        });
        group.appendChild(conv.g);

        // USBStreamer
        var usb = buildNode({
            id: "gv-node-usbstreamer", label: "USBStreamer", color: "hw",
            x: usbX, y: usbY,
            inputs: usbIns, outputs: [],
            state: "active"
        });
        group.appendChild(usb.g);

        // Links
        var linksGroup = svgCreate("g");

        // UMIK-1 capture -> Signal-gen mic (missing until UMIK-1 connected)
        linksGroup.appendChild(buildLink(
            umik.outputPorts[0].cx, umik.outputPorts[0].cy,
            siggen.inputPorts[0].cx, siggen.inputPorts[0].cy,
            "gv-link--missing", "gv-arrow"
        ));

        // Signal-gen ch0-3 -> Convolver AUX0-3
        for (var i = 0; i < 4; i++) {
            linksGroup.appendChild(buildLink(
                siggen.outputPorts[i].cx, siggen.outputPorts[i].cy,
                conv.inputPorts[i].cx, conv.inputPorts[i].cy,
                "gv-link--connected", "gv-arrow"
            ));
        }

        // Convolver -> USBStreamer ch1-4
        for (var j = 0; j < 4; j++) {
            linksGroup.appendChild(buildLink(
                conv.outputPorts[j].cx, conv.outputPorts[j].cy,
                usb.inputPorts[j].cx, usb.inputPorts[j].cy,
                "gv-link--connected", "gv-arrow"
            ));
        }

        group.insertBefore(linksGroup, umik.g);

        return group;
    }

    // -- Template selection --

    var templates = {
        monitoring: buildMonitoringTemplate,
        dj: buildDjTemplate,
        live: buildLiveTemplate,
        measurement: buildMeasurementTemplate
    };

    function renderTemplate(mode) {
        if (!svgEl) return;

        // Clear existing content (keep defs)
        var children = svgEl.childNodes;
        for (var i = children.length - 1; i >= 0; i--) {
            if (children[i].tagName !== "defs") {
                svgEl.removeChild(children[i]);
            }
        }

        // Mode label
        var modeLabel = svgText(12, 18, (mode || "").toUpperCase(), "gv-mode-label");
        modeLabel.id = "gv-mode-label";
        svgEl.appendChild(modeLabel);

        // Build template
        var builderFn = templates[mode];
        if (builderFn) {
            var templateGroup = builderFn();
            svgEl.appendChild(templateGroup);
        }

        currentMode = mode;
        fitViewBox();
    }

    function fitViewBox() {
        if (!svgEl) return;
        try {
            var bbox = svgEl.getBBox();
            if (bbox.width > 0 && bbox.height > 0) {
                var pad = 12;
                var vbX = Math.max(0, bbox.x - pad);
                var vbY = Math.max(0, bbox.y - pad);
                var vbW = bbox.width + pad * 2;
                var vbH = bbox.height + pad * 2;
                svgEl.setAttribute("viewBox", vbX + " " + vbY + " " + vbW + " " + vbH);
            }
        } catch (e) {
            // getBBox fails if SVG not visible (display: none)
        }
    }

    // -- GM node name constants (from routing.rs, architect spec) --

    var GM_NODES = {
        mixxx:          { match: "prefix", pattern: "Mixxx" },
        reaper:         { match: "prefix", pattern: "REAPER" },
        convolver:      { match: "exact",  pattern: "pi4audio-convolver" },
        convolverOut:   { match: "exact",  pattern: "pi4audio-convolver-out" },
        usbPlayback:    { match: "prefix", pattern: "alsa_output.usb-MiniDSP_USBStreamer" },
        siggen:         { match: "exact",  pattern: "pi4audio-signal-gen" },
        siggenCapture:  { match: "exact",  pattern: "pi4audio-signal-gen-capture" },
        ada8200:        { match: "exact",  pattern: "ada8200-in" },
        umik1:          { match: "prefix", pattern: "alsa_input.usb-miniDSP_UMIK-1" }
    };

    // Map SVG node IDs to GM node name matchers
    var NODE_ID_TO_GM = {
        "gv-node-mixxx":        [GM_NODES.mixxx],
        "gv-node-reaper":       [GM_NODES.reaper],
        "gv-node-convolver":    [GM_NODES.convolver, GM_NODES.convolverOut],
        "gv-node-usbstreamer":  [GM_NODES.usbPlayback],
        "gv-node-siggen":       [GM_NODES.siggen, GM_NODES.siggenCapture],
        "gv-node-ada8200":      [GM_NODES.ada8200],
        "gv-node-umik1":        [GM_NODES.umik1]
    };

    // Map device keys (from GM get_state devices) to SVG node IDs
    var DEVICE_TO_NODE = {
        usbstreamer:     "gv-node-usbstreamer",
        umik1:           "gv-node-umik1",
        convolver:       "gv-node-convolver",
        "convolver-out": "gv-node-convolver"
    };

    function gmNodeMatch(gmName, matcher) {
        if (matcher.match === "exact") return gmName === matcher.pattern;
        return gmName.indexOf(matcher.pattern) === 0;
    }

    // -- Data handler (from /ws/system) --

    function onSystemData(data) {
        // Prefer new graph section; fall back to legacy camilladsp fields
        var graph = data.graph || null;
        var mode;
        if (graph) {
            mode = graph.mode || "monitoring";
        } else {
            mode = data.mode || (data.camilladsp && data.camilladsp.gm_mode) || "monitoring";
        }

        if (mode !== currentMode) {
            renderTemplate(mode);
        }

        if (graph) {
            updateDeviceStates(graph.devices || {});
            updateLinkStates(graph.link_details || []);
        } else {
            updateLegacyStates(data.camilladsp || {});
        }
    }

    function updateDeviceStates(devices) {
        for (var devKey in DEVICE_TO_NODE) {
            var nodeId = DEVICE_TO_NODE[devKey];
            var el = document.getElementById(nodeId);
            if (!el) continue;
            var status = devices[devKey] || "unknown";
            el.classList.remove("gv-node--active", "gv-node--absent", "gv-node--error");
            if (status === "present" || status === "connected") {
                el.classList.add("gv-node--active");
            } else {
                el.classList.add("gv-node--absent");
            }
        }
    }

    function updateLinkStates(links) {
        if (!svgEl) return;

        // Reset all ports to idle
        var ports = svgEl.querySelectorAll(".gv-port");
        for (var p = 0; p < ports.length; p++) {
            ports[p].classList.remove("gv-port--connected");
            ports[p].classList.add("gv-port--idle");
        }

        // Mark active ports and track health
        var hasMissing = false;
        for (var i = 0; i < links.length; i++) {
            var lnk = links[i];
            if (lnk.status === "missing" || lnk.status === "failed") {
                hasMissing = true;
            }
            if (lnk.status === "active") {
                markPortConnected(lnk.output_node, lnk.output_port, "output");
                markPortConnected(lnk.input_node, lnk.input_port, "input");
            }
        }

        // Mode label turns red if any links missing/failed
        var modeLabel = document.getElementById("gv-mode-label");
        if (modeLabel) {
            modeLabel.setAttribute("fill", hasMissing ? "#e5453a" : "");
        }
    }

    function markPortConnected(nodeName, portName, direction) {
        for (var nodeId in NODE_ID_TO_GM) {
            var matchers = NODE_ID_TO_GM[nodeId];
            var matched = false;
            for (var m = 0; m < matchers.length; m++) {
                if (gmNodeMatch(nodeName, matchers[m])) { matched = true; break; }
            }
            if (!matched) continue;

            var nodeEl = document.getElementById(nodeId);
            if (!nodeEl) continue;

            var portClass = direction === "input" ? "gv-port--input" : "gv-port--output";
            var portEls = nodeEl.querySelectorAll("." + portClass);
            for (var p = 0; p < portEls.length; p++) {
                var dp = portEls[p].getAttribute("data-port");
                if (dp && (portName.indexOf(dp) !== -1 || dp.indexOf(portName) !== -1)) {
                    portEls[p].classList.remove("gv-port--idle");
                    portEls[p].classList.add("gv-port--connected");
                }
            }
        }
    }

    function updateLegacyStates(cdsp) {
        var convEl = document.getElementById("gv-node-convolver");
        if (convEl) {
            var convStatus = cdsp.gm_convolver || "unknown";
            convEl.classList.remove("gv-node--active", "gv-node--absent", "gv-node--error");
            if (convStatus === "present" || convStatus === "connected") {
                convEl.classList.add("gv-node--active");
            } else {
                convEl.classList.add("gv-node--absent");
            }
        }

        var missing = cdsp.gm_links_missing || 0;
        var modeLabel = document.getElementById("gv-mode-label");
        if (modeLabel) {
            modeLabel.setAttribute("fill", missing > 0 ? "#e5453a" : "");
        }
    }

    // -- View lifecycle --

    function init() {
        svgEl = document.getElementById("gv-svg");
        if (!svgEl) return;

        // Add marker definitions
        svgEl.appendChild(buildDefs());

        // Render default template (monitoring)
        renderTemplate("monitoring");
    }

    function onShow() {
        // Re-render current template in case data changed while hidden
        if (currentMode) {
            renderTemplate(currentMode);
        }
        // Fit viewBox now that SVG is visible (getBBox needs display != none)
        fitViewBox();
    }

    function onHide() {
        // Nothing to stop (no animation loop)
    }

    // -- Register --
    // View for lifecycle; global consumer for /ws/system data.
    // system.js owns the /ws/system WebSocket connection.
    // Global consumer receives dispatched data without opening a second socket.

    PiAudio.registerView("graph", {
        init: init,
        onShow: onShow,
        onHide: onHide
    });

    PiAudio.registerGlobalConsumer("graph", {
        onSystem: onSystemData
    });

})();
