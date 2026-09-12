import readline from "node:readline";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const controllerPath = path.resolve(__dirname, "../../external/browserControl/dist/controller.js");

let ChromeController;
try {
  const mod = await import(controllerPath);
  ChromeController = mod.ChromeController;
} catch (err) {
  process.stderr.write(`Failed to load ChromeController from ${controllerPath}: ${err}\n`);
  process.exit(1);
}

let controller = null;

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false,
});

function sendResponse(id, payload) {
  const resp = JSON.stringify({ id, ...payload });
  process.stdout.write(resp + "\n");
}

async function evalJs(expr) {
  if (!controller || !controller.session) {
    throw new Error("No active session for evaluation");
  }
  const resp = await controller.session.send("Runtime.evaluate", {
    expression: expr,
    returnByValue: true,
  });
  return resp?.result?.value;
}

rl.on("line", async (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;

  let req;
  try {
    req = JSON.parse(trimmed);
  } catch (err) {
    sendResponse(0, { success: false, errorCode: "INVALID_JSON", error: String(err) });
    return;
  }

  const { id, action, params = {} } = req;

  try {
    switch (action) {
      case "init":
      case "connect": {
        if (controller) {
          await controller.disconnect().catch(() => {});
        }
        controller = new ChromeController({
          mode: params.mode || (params.wsEndpoint ? "ws-endpoint" : params.browserUrl ? "browser-url" : "auto"),
          browserUrl: params.browserUrl,
          wsEndpoint: params.wsEndpoint,
        });
        await controller.connect(params.targetId);
        sendResponse(id, {
          success: true,
          data: {
            targetId: controller.currentTargetId,
            visualEpoch: controller.session?.visualEpoch,
            connected: controller.isConnected,
          },
        });
        break;
      }

      case "disconnect": {
        if (controller) {
          await controller.disconnect().catch(() => {});
          controller = null;
        }
        sendResponse(id, { success: true, data: { disconnected: true } });
        break;
      }

      case "observe": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const obs = await controller.observe(params);
        sendResponse(id, {
          success: true,
          data: {
            observationId: obs.observationId,
            visualEpoch: obs.visualEpoch,
            viewportWidth: obs.viewportWidth,
            viewportHeight: obs.viewportHeight,
            imageWidth: obs.imageWidth,
            imageHeight: obs.imageHeight,
            image: obs.image,
          },
        });
        break;
      }

      case "click": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeComputerAction({
          type: "click",
          observationId: params.observationId,
          x: params.x,
          y: params.y,
          button: params.button || "left",
          modifiers: params.modifiers || [],
        });
        sendResponse(id, res);
        break;
      }

      case "double_click": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeComputerAction({
          type: "double_click",
          observationId: params.observationId,
          x: params.x,
          y: params.y,
          button: params.button || "left",
          modifiers: params.modifiers || [],
        });
        sendResponse(id, res);
        break;
      }

      case "type": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeComputerAction({
          type: "type",
          observationId: params.observationId,
          text: params.text,
          method: params.method,
        });
        sendResponse(id, res);
        break;
      }

      case "scroll": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeComputerAction({
          type: "scroll",
          observationId: params.observationId,
          x: params.x !== undefined ? params.x : 100,
          y: params.y !== undefined ? params.y : 100,
          deltaX: params.deltaX || 0,
          deltaY: params.deltaY || 0,
        });
        sendResponse(id, res);
        break;
      }

      case "navigate": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeBrowserAction({
          type: "navigate",
          url: params.url,
        });
        sendResponse(id, res);
        break;
      }

      case "back": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeBrowserAction({ type: "back" });
        sendResponse(id, res);
        break;
      }

      case "forward": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeBrowserAction({ type: "forward" });
        sendResponse(id, res);
        break;
      }

      case "reload": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeBrowserAction({ type: "reload" });
        sendResponse(id, res);
        break;
      }

      case "tabs": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const tabs = await controller.getTabs();
        sendResponse(id, { success: true, data: tabs });
        break;
      }

      case "new_tab": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeBrowserAction({
          type: "new_tab",
          url: params.url || "about:blank",
        });
        sendResponse(id, res);
        break;
      }

      case "switch_tab": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeBrowserAction({
          type: "switch_tab",
          targetId: params.targetId,
        });
        sendResponse(id, res);
        break;
      }

      case "close_tab": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const res = await controller.executeBrowserAction({
          type: "close_tab",
          targetId: params.targetId,
        });
        sendResponse(id, res);
        break;
      }

      case "evaluate": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const val = await evalJs(params.expression);
        sendResponse(id, { success: true, data: val });
        break;
      }

      case "doctor": {
        if (!controller) throw { errorCode: "NOT_CONNECTED", message: "Controller not connected" };
        const doc = await controller.doctor();
        sendResponse(id, { success: true, data: doc });
        break;
      }

      case "exit": {
        if (controller) {
          await controller.disconnect().catch(() => {});
        }
        sendResponse(id, { success: true, data: { exit: true } });
        process.exit(0);
        break;
      }

      default: {
        sendResponse(id, {
          success: false,
          errorCode: "UNKNOWN_ACTION",
          error: `Unrecognized action: ${action}`,
        });
        break;
      }
    }
  } catch (err) {
    sendResponse(id, {
      success: false,
      errorCode: err?.errorCode || "UNHANDLED_ERROR",
      error: err?.message || String(err),
    });
  }
});

process.on("SIGINT", async () => {
  if (controller) await controller.disconnect().catch(() => {});
  process.exit(0);
});
process.on("SIGTERM", async () => {
  if (controller) await controller.disconnect().catch(() => {});
  process.exit(0);
});
