async (page) => {
  await page.getByRole('textbox', { name: 'LinkedIn Profile' }).fill('https://linkedin.com/in/harxhist');
  await page.getByRole('textbox', { name: 'Github' }).fill('https://github.com/harxhist');
  await page.getByRole('textbox', { name: 'Website' }).fill('https://har.sh10.in');
  await page.waitForTimeout(400);

  async function selectCombo(nameRe, optionText) {
    const combo = page.getByRole('combobox', { name: nameRe });
    await combo.scrollIntoViewIfNeeded();
    await combo.click();
    await page.waitForTimeout(500);
    await page.getByRole('option', { name: optionText, exact: true }).click();
    await page.waitForTimeout(600);
  }

  await selectCombo(/Job Applicant Privacy Notice/, 'Acknowledge/Confirm');
  await selectCombo(/double-check all the information/, 'I have reviewed and confirmed that all the information provided is accurate and complete.');
  await selectCombo(/first hear about this role/, 'Other job boards');

  return await page.evaluate(() => ({
    linkedin: document.querySelector('#question_14587797004')?.value,
    github: document.querySelector('#question_14587799004')?.value,
    website: document.querySelector('#question_14587800004')?.value,
    singles: Array.from(document.querySelectorAll('.select__single-value')).map(e => e.textContent.trim()),
    resume: document.body.innerText.includes('Harsh_Rajput_Resume'),
    preferred: document.querySelector('#preferred_name')?.value
  }));
}
