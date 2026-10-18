import { changeSetting, useSettings } from "../../settings";

// Debugging options for the kitchen. Each toggle makes checks slower, so all start off.
export function SettingsMenu() {
  const settings = useSettings();

  return <details className="settings-menu">
    <summary>Settings</summary>
    <div className="settings-panel">
      <p className="settings-note">These help with debugging but make each check slower.</p>
      <label><input type="checkbox" checked={settings.boxes} onChange={event => changeSetting("boxes", event.target.checked)} />
        <span>Boxes and labels in CV logs<small>Perceptron also says where each item is.</small></span></label>
      <label><input type="checkbox" checked={settings.photos} onChange={event => changeSetting("photos", event.target.checked)} />
        <span>Model input in CV logs<small>The exact photo and menu references Perceptron got.</small></span></label>
    </div>
  </details>;
}
