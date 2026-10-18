import { changeSetting, useSettings, type Reasoning } from "../../settings";

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
      <label><select value={settings.reasoning} onChange={event => changeSetting("reasoning", event.target.value as Reasoning)}>
        <option value="auto">Auto</option><option value="none">None</option><option value="low">Low</option><option value="high">High</option>
      </select>
        <span>Model reasoning<small>Auto thinks harder for orders of 4+ items. The others force one mode.</small></span></label>
    </div>
  </details>;
}
