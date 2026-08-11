cube(`Deposits`, {
  sql: `SELECT * FROM test.cai_deposits`,

  measures: {
    count: {
      type: `count`
    },
    totalPrincipal: {
      sql: `principal_amount`,
      type: `sum`
    },
    avgInterestRate: {
      sql: `interest_rate`,
      type: `avg`
    }
  },

  dimensions: {
    depositId: {
      sql: `deposit_id`,
      type: `number`,
      primaryKey: true
    },
    customerId: {
      sql: `customer_id`,
      type: `number`
    },
    accountNumber: {
      sql: `account_number`,
      type: `string`
    },
    status: {
      sql: `status`,
      type: `string`
    },
    maturityDate: {
      sql: `maturity_date`,
      type: `time`
    }
  }
});