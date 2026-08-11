async (page) => {
  const resume = '/Users/hr/Documents/vault/00switch/job_search/ApplyPilot/Harsh_Rajput_Resume.docx';
  const cover = '/Users/hr/Documents/vault/00switch/job_search/ApplyPilot/Harsh_Rajput_Cover_Letter.docx';

  await page.getByRole('textbox', { name: 'First Name', exact: true }).fill('Harsh');
  await page.getByRole('textbox', { name: 'Last Name' }).fill('Rajput');
  await page.getByRole('textbox', { name: 'Preferred First Name' }).fill('Harsh');
  await page.getByRole('textbox', { name: 'Email' }).fill('harxhist@gmail.com');

  // Country India
  await page.getByRole('combobox', { name: 'Country', exact: true }).click();
  await page.waitForTimeout(500);
  await page.getByRole('combobox', { name: 'Country', exact: true }).pressSequentially('India', { delay: 50 });
  await page.waitForTimeout(800);
  await page.getByRole('option', { name: 'India +91', exact: true }).click();
  await page.waitForTimeout(500);

  await page.getByRole('textbox', { name: 'Phone' }).fill('7217016717');

  // Location
  await page.getByRole('combobox', { name: 'Location (City)' }).click();
  await page.waitForTimeout(300);
  await page.getByRole('combobox', { name: 'Location (City)' }).pressSequentially('Delhi', { delay: 80 });
  await page.waitForTimeout(2000);
  await page.getByRole('option', { name: 'Delhi, India', exact: true }).click();
  await page.waitForTimeout(500);

  // Resume upload
  const [fileChooser1] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.getByLabel('Resume/CV*').getByText('Attach', { exact: true }).first().click()
  ]);
  await fileChooser1.setFiles(resume);
  await page.waitForTimeout(2000);

  // Cover letter
  const [fileChooser2] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.getByLabel('Cover Letter').getByText('Attach', { exact: true }).first().click()
  ]);
  await fileChooser2.setFiles(cover);
  await page.waitForTimeout(1500);

  await page.getByRole('textbox', { name: 'LinkedIn Profile' }).fill('https://linkedin.com/in/harxhist');
  await page.getByRole('textbox', { name: 'Website' }).fill('https://har.sh10.in');
  await page.getByRole('textbox', { name: 'How did you hear about this' }).fill('Online Job Board');

  // Helper for react-select
  async function selectCombo(name, optionText) {
    await page.getByRole('combobox', { name }).click();
    await page.waitForTimeout(400);
    await page.getByRole('option', { name: optionText, exact: true }).click();
    await page.waitForTimeout(400);
  }

  await selectCombo('Are you legally authorized to', 'Yes');
  await selectCombo('Do you now or will you in the', 'No');
  await selectCombo('Do you currently or have you', 'No');

  await page.getByRole('checkbox', { name: 'None of the above', exact: true }).click();
  await page.waitForTimeout(300);
  await page.getByRole('checkbox', { name: 'Not applicable (i.e., I' }).click();
  await page.waitForTimeout(300);

  await selectCombo('Gender', 'Male');
  await selectCombo('Are you Hispanic/Latino?', 'No');
  await selectCombo('Please identify your race', 'Asian');
  await selectCombo('Veteran Status', 'I am not a protected veteran');
  await selectCombo('Disability Status', 'No, I do not have a disability and have not had one in the past');

  // Verify key fields
  const summary = await page.evaluate(() => {
    const singles = Array.from(document.querySelectorAll('.select__single-value')).map(e => e.textContent);
    return {
      first: document.querySelector('input[name="first_name"], #first_name')?.value,
      email: document.querySelector('input[type="email"], #email')?.value,
      singles,
      resume: document.body.innerText.includes('Harsh_Rajput_Resume'),
      cover: document.body.innerText.includes('Harsh_Rajput_Cover_Letter'),
    };
  });
  return summary;
}
