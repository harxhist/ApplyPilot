async (page) => {
  // Basic fields
  await page.getByRole('textbox', { name: 'First Name', exact: true }).fill('Harsh');
  await page.getByRole('textbox', { name: 'Last Name' }).fill('Rajput');
  await page.getByRole('textbox', { name: 'Preferred First Name' }).fill('Harsh');
  await page.getByRole('textbox', { name: 'Email' }).fill('harxhist@gmail.com');
  await page.waitForTimeout(500);

  // Country - click and select India
  const country = page.getByRole('combobox', { name: 'Country', exact: true });
  await country.click();
  await page.waitForTimeout(400);
  await country.pressSequentially('India', { delay: 50 });
  await page.waitForTimeout(800);
  await page.getByRole('option', { name: /^India/ }).first().click();
  await page.waitForTimeout(500);

  // Phone
  await page.getByRole('textbox', { name: 'Phone' }).fill('7217016717');
  await page.waitForTimeout(500);

  // Resume upload
  const [fileChooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.locator('button').filter({ hasText: 'Attach' }).first().click()
  ]);
  await fileChooser.setFiles('/Users/hr/Documents/vault/00switch/job_search/ApplyPilot/Harsh_Rajput_Resume.docx');
  await page.waitForTimeout(2000);

  async function selectCombo(nameRe, optionText) {
    const combo = page.getByRole('combobox', { name: nameRe });
    await combo.scrollIntoViewIfNeeded();
    await combo.click();
    await page.waitForTimeout(500);
    await page.getByRole('option', { name: optionText, exact: true }).click();
    await page.waitForTimeout(600);
  }

  await selectCombo(/currently based in any/, 'India');
  await selectCombo(/Visa Sponsorship/, 'Yes');
  await selectCombo(/authorization to work/, 'I am authorized to work in the country due to my nationality');
  await selectCombo(/live in one of the following states/, 'No');

  await page.getByRole('textbox', { name: 'LinkedIn Profile' }).fill('https://linkedin.com/in/harxhist');
  await page.getByRole('textbox', { name: 'Github' }).fill('https://github.com/harxhist');
  await page.getByRole('textbox', { name: 'Website' }).fill('https://har.sh10.in');
  await page.waitForTimeout(400);

  await selectCombo(/Job Applicant Privacy Notice/, 'Acknowledge/Confirm');
  await selectCombo(/double-check all the information/, 'I have reviewed and confirmed that all the information provided is accurate and complete.');
  await selectCombo(/first hear about this role/, 'Other job boards');

  const values = await page.evaluate(() => ({
    first: document.querySelector('#first_name')?.value,
    last: document.querySelector('#last_name')?.value,
    email: document.querySelector('#email')?.value,
    phone: document.querySelector('#phone')?.value,
    linkedin: document.querySelector('#question_14587797004')?.value,
    github: document.querySelector('#question_14587799004')?.value,
    singles: Array.from(document.querySelectorAll('.select__single-value')).map(e => e.textContent.trim()),
    resume: document.body.innerText.includes('Harsh_Rajput_Resume'),
    url: location.href
  }));
  return values;
}
