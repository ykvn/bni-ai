cube(`Orders`, {
  // This raw SQL creates a temporary table with 3 fake rows on the fly
  sql: `SELECT 1 as id, 100 as amount, 'completed' as status 
        UNION ALL 
        SELECT 2 as id, 250 as amount, 'pending' as status 
        UNION ALL 
        SELECT 3 as id, 75 as amount, 'completed' as status`,

  measures: {
    count: {
      type: `count`
    },
    totalAmount: {
      sql: `amount`,
      type: `sum`
    }
  },

  dimensions: {
    id: {
      sql: `id`,
      type: `number`,
      primaryKey: true
    },
    status: {
      sql: `status`,
      type: `string`
    }
  }
});