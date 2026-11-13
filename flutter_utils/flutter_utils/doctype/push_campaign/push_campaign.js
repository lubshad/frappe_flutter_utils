frappe.ui.form.on("Push Campaign", {
	async onload(frm) {
		const { message } = await frappe.call({
			method: "flutter_utils.api.campaigns.get_user_fields",
		});
		frm.campaign_user_fields = message || [];
		frm.fields_dict.audience_filters.grid.update_docfield_property("user_field", "options",
			frm.campaign_user_fields.map((field) => ({
				value: field.fieldname,
				label: `${field.label} (${field.fieldname})`,
			})));
	},
	refresh(frm) {
		const draft = frm.doc.status === "Draft";
		for (const field of ["campaign_name", "app", "push_title", "push_body", "match_mode",
			"audience_filters", "send_mode", "timezone", "start_date", "send_time", "frequency", "end_date"]) {
			frm.set_df_property(field, "read_only", !draft);
		}
		if (!draft) frm.disable_save();
		if (draft) frm.add_custom_button(__("Add Audience Condition"), () => add_campaign_condition(frm));
		if (frm.is_new()) return;
		const saved = () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save your changes first."));
				return false;
			}
			return true;
		};
		frm.add_custom_button(__("Preview Audience"), async () => {
			if (!saved()) return;
			const { message: result } = await frappe.call({
				method: "flutter_utils.api.campaigns.preview", args: { name: frm.doc.name }, freeze: true,
				freeze_message: __("Checking audience…"),
			});
			const escape = frappe.utils.escape_html;
			frappe.msgprint({ title: __("Audience Preview"), message:
				`<p>${__("Matched users")}: ${result.matched_users}<br>` +
				`${__("Users with eligible devices")}: ${result.eligible_users}<br>` +
				`${__("Eligible devices")}: ${result.eligible_devices}</p>` +
				`<p>${__("Sample (up to 20 matching users)")}</p>` +
				(result.sample.length ? `<ul>${result.sample.map((user) =>
					`<li>${escape(user.full_name || user.name)} — ${escape(user.name)}</li>`).join("")}</ul>` :
					`<p>${__("No users match. Adjust the audience conditions.")}</p>`) +
				`<p>${__("The audience will be checked again when the campaign runs.")}</p>`,
			});
		});
		const actions = { Draft: [["start", "Start Campaign"], ["cancel", "Cancel Campaign"]],
			Active: [["pause", "Pause Campaign"], ["cancel", "Cancel Campaign"]],
			Paused: [["resume", "Resume Campaign"], ["cancel", "Cancel Campaign"]] };
		for (const [action, label] of actions[frm.doc.status] || []) {
			frm.add_custom_button(__(label), () => {
				if (!saved()) return;
				const note = ["cancel", "pause"].includes(action)
					? __("Messages already being sent cannot be recalled.")
					: __("This authorizes push messages to all eligible devices in the selected audience.");
				frappe.confirm(__("{0}: {1}?", [__(label), frappe.utils.escape_html(frm.doc.campaign_name)]) +
					`<br>${note}`, async () => {
					await frappe.call({ method: "flutter_utils.api.campaigns.action",
						args: { name: frm.doc.name, action }, freeze: true });
					await frm.reload_doc();
				});
			}, __("Campaign"));
		}
		frm.add_custom_button(__("Run History"), () =>
			frappe.set_route("List", "Push Campaign Run", { campaign: frm.doc.name }));
	},
});

function configure_campaign_condition(frm, cdt, cdn) {
	const doc = locals[cdt][cdn];
	const field = (frm.campaign_user_fields || []).find((item) => item.fieldname === doc.user_field);
	const row = frm.fields_dict.audience_filters.grid.grid_rows_by_docname[cdn];
	if (!field || !row) return;
	const operator = row.docfields.find((item) => item.fieldname === "operator");
	operator.options = field.operators.join("\n");
	const value = row.docfields.find((item) => item.fieldname === "value");
	const unset = ["is set", "is not set"].includes(doc.operator);
	value.read_only = unset;
	row.refresh();
}

function add_campaign_condition(frm) {
	const fields = frm.campaign_user_fields || [];
	if (!fields.length) {
		frappe.msgprint(__("User fields are not loaded. Reload the form and try again."));
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Choose User Condition"),
		fields: [
			{ fieldname: "user_field", label: __("User Field"), fieldtype: "Autocomplete", reqd: 1,
				options: fields.map((field) => ({ value: field.fieldname, label: `${field.label} (${field.fieldname})` })),
				onchange() {
					const field = fields.find((item) => item.fieldname === dialog.get_value("user_field"));
					dialog.set_df_property("operator", "options", (field?.operators || ["="]).join("\n"));
					dialog.set_value("operator", "=");
				} },
			{ fieldname: "operator", label: __("Operator"), fieldtype: "Select", options: "=", reqd: 1 },
		],
		primary_action_label: __("Continue"),
		primary_action(values) {
			const field = fields.find((item) => item.fieldname === values.user_field);
			if (!field) return;
			const append = (value) => {
				frm.add_child("audience_filters", { ...values, value: String(value ?? "") });
				frm.refresh_field("audience_filters");
				frm.dirty();
			};
			dialog.hide();
			if (["is set", "is not set"].includes(values.operator)) {
				append("");
				return;
			}
			const multiple = ["in", "not in", "contains"].includes(values.operator);
			const fieldtype = multiple ? "Data" : field.fieldtype;
			frappe.prompt([{
				fieldname: "value", label: field.label, fieldtype, reqd: fieldtype !== "Check",
				options: ["Link", "Select"].includes(fieldtype) ? field.options : undefined,
				description: ["in", "not in"].includes(values.operator) ? __("Enter comma-separated values.") : undefined,
			}], (result) => append(result.value), __("Condition Value"), __("Add Condition"));
		},
	});
	dialog.show();
}

frappe.ui.form.on("Push Campaign Filter", {
	async user_field(frm, cdt, cdn) {
		await frappe.model.set_value(cdt, cdn, { operator: "=", value: "" });
		configure_campaign_condition(frm, cdt, cdn);
	},
	operator: configure_campaign_condition,
	form_render: configure_campaign_condition,
});
