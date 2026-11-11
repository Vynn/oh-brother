// What a click on Print will send

// Printing more labels than this asks first. Loading a data file ticks every
// row, so one click could otherwise send the whole file to the printer.
export const CONFIRM_ABOVE = 25;

// The ticked data rows, in order, or null without data (one label from fixed values).
// data: the loaded data file or null; picked: the set of ticked row indexes.
export const jobRows = (data, picked) => data ? [...picked].sort((a, b) => a - b) : null;

// Copies as the server will take them: a whole number from 1 to its limit
export const copiesOf = (value, limit) => Math.max(1, Math.min(limit, Math.floor(+value || 1)));

export const labelCount = (data, picked, copies) => (data ? picked.size : 1) * copies;
