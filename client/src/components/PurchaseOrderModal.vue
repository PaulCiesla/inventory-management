<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="modal-overlay" @click="close">
        <div class="modal-container" @click.stop>
          <div class="modal-header">
            <h3 class="modal-title">
              {{ mode === 'view' ? t('purchaseOrder.viewTitle') : t('purchaseOrder.createTitle') }}
            </h3>
            <button class="close-button" @click="close">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <div v-if="backlogItem" class="item-summary">
              <div class="summary-field">
                <span class="summary-label">{{ t('purchaseOrder.sku') }}</span>
                <span class="summary-value">{{ backlogItem.item_sku }}</span>
              </div>
              <div class="summary-field">
                <span class="summary-label">{{ t('purchaseOrder.item') }}</span>
                <span class="summary-value">{{ translateProductName(backlogItem.item_name) }}</span>
              </div>
              <div class="summary-field">
                <span class="summary-label">{{ t('purchaseOrder.shortage') }}</span>
                <span class="summary-value danger">{{ shortage }}</span>
              </div>
            </div>

            <!-- View mode -->
            <div v-if="mode === 'view'">
              <div v-if="loading" class="state-message">{{ t('purchaseOrder.loading') }}</div>
              <div v-else-if="error" class="state-message error">{{ error }}</div>
              <div v-else-if="purchaseOrder" class="po-details">
                <div class="detail-row">
                  <span class="detail-label">{{ t('purchaseOrder.poNumber') }}</span>
                  <span class="detail-value"><strong>{{ purchaseOrder.id }}</strong></span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">{{ t('purchaseOrder.supplier') }}</span>
                  <span class="detail-value">{{ purchaseOrder.supplier_name }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">{{ t('purchaseOrder.quantity') }}</span>
                  <span class="detail-value">{{ purchaseOrder.quantity.toLocaleString() }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">{{ t('purchaseOrder.unitCost') }}</span>
                  <span class="detail-value">{{ formatCurrency(purchaseOrder.unit_cost, currentCurrency) }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">{{ t('purchaseOrder.total') }}</span>
                  <span class="detail-value">
                    <strong>{{ formatCurrency(purchaseOrder.quantity * purchaseOrder.unit_cost, currentCurrency) }}</strong>
                  </span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">{{ t('purchaseOrder.expectedDelivery') }}</span>
                  <span class="detail-value">{{ purchaseOrder.expected_delivery_date }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">{{ t('purchaseOrder.createdDate') }}</span>
                  <span class="detail-value">{{ purchaseOrder.created_date }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">{{ t('purchaseOrder.status') }}</span>
                  <span class="detail-value">
                    <span class="badge">{{ purchaseOrder.status }}</span>
                  </span>
                </div>
                <div v-if="purchaseOrder.notes" class="detail-row">
                  <span class="detail-label">{{ t('purchaseOrder.notes') }}</span>
                  <span class="detail-value">{{ purchaseOrder.notes }}</span>
                </div>
              </div>
            </div>

            <!-- Create mode -->
            <div v-else class="po-form">
              <div class="form-row">
                <div class="form-group">
                  <label for="po-supplier">{{ t('purchaseOrder.supplier') }}</label>
                  <input
                    id="po-supplier"
                    v-model="form.supplier_name"
                    type="text"
                    class="po-input"
                    :placeholder="t('purchaseOrder.supplierPlaceholder')"
                  />
                </div>
              </div>

              <div class="form-row">
                <div class="form-group">
                  <label for="po-quantity">{{ t('purchaseOrder.quantity') }}</label>
                  <input id="po-quantity" v-model.number="form.quantity" type="number" min="1" class="po-input" />
                </div>
                <div class="form-group">
                  <label for="po-unit-cost">{{ t('purchaseOrder.unitCostInput') }}</label>
                  <input id="po-unit-cost" v-model.number="form.unit_cost" type="number" min="0" step="0.01" class="po-input" />
                </div>
                <div class="form-group">
                  <label for="po-delivery">{{ t('purchaseOrder.expectedDelivery') }}</label>
                  <input id="po-delivery" v-model="form.expected_delivery_date" type="date" class="po-input" />
                </div>
              </div>

              <div class="form-row">
                <div class="form-group">
                  <label for="po-notes">{{ t('purchaseOrder.notes') }}</label>
                  <input
                    id="po-notes"
                    v-model="form.notes"
                    type="text"
                    class="po-input"
                    :placeholder="t('purchaseOrder.notesPlaceholder')"
                  />
                </div>
              </div>

              <div class="form-total">
                <span>{{ t('purchaseOrder.total') }}</span>
                <strong>{{ formatCurrency(estimatedTotal, currentCurrency) }}</strong>
              </div>

              <div v-if="error" class="state-message error">{{ error }}</div>
            </div>
          </div>

          <div class="modal-footer">
            <button class="btn-secondary" @click="close">
              {{ mode === 'view' ? t('purchaseOrder.close') : t('purchaseOrder.cancel') }}
            </button>
            <button v-if="mode !== 'view'" class="btn-primary" :disabled="!canSubmit || submitting" @click="submit">
              {{ submitting ? t('purchaseOrder.creating') : t('purchaseOrder.create') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script>
import { ref, computed, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

// Suppliers aren't modelled in the backend, so the PO lead time is a flat
// two-week default the user can override before submitting.
const DEFAULT_LEAD_TIME_DAYS = 14

export default {
  name: 'PurchaseOrderModal',
  props: {
    isOpen: {
      type: Boolean,
      required: true
    },
    backlogItem: {
      type: Object,
      default: null
    },
    mode: {
      type: String,
      default: 'create'
    }
  },
  emits: ['close', 'po-created'],
  setup(props, { emit }) {
    const { t, currentCurrency, translateProductName } = useI18n()

    const loading = ref(false)
    const submitting = ref(false)
    const error = ref(null)
    const purchaseOrder = ref(null)

    const emptyForm = () => ({
      supplier_name: '',
      quantity: 0,
      unit_cost: 0,
      expected_delivery_date: '',
      notes: ''
    })
    const form = ref(emptyForm())

    const shortage = computed(() => {
      if (!props.backlogItem) return 0
      return Math.abs(props.backlogItem.quantity_needed - props.backlogItem.quantity_available)
    })

    const estimatedTotal = computed(() => {
      const qty = Number(form.value.quantity) || 0
      const cost = Number(form.value.unit_cost) || 0
      return qty * cost
    })

    const canSubmit = computed(() => {
      return Boolean(
        props.backlogItem &&
        form.value.supplier_name.trim() &&
        Number(form.value.quantity) > 0 &&
        Number(form.value.unit_cost) >= 0 &&
        form.value.expected_delivery_date
      )
    })

    const defaultDeliveryDate = () => {
      const date = new Date()
      date.setDate(date.getDate() + DEFAULT_LEAD_TIME_DAYS)
      return date.toISOString().slice(0, 10)
    }

    const loadPurchaseOrder = async () => {
      if (!props.backlogItem) return
      try {
        loading.value = true
        error.value = null
        purchaseOrder.value = await api.getPurchaseOrderByBacklogItem(props.backlogItem.id)
      } catch (err) {
        error.value = t('purchaseOrder.loadError')
        console.error('Failed to load purchase order:', err)
      } finally {
        loading.value = false
      }
    }

    // Reset per open so a cancelled draft never leaks into the next backlog row.
    watch(
      () => [props.isOpen, props.mode, props.backlogItem],
      () => {
        if (!props.isOpen) return
        error.value = null
        purchaseOrder.value = null

        if (props.mode === 'view') {
          loadPurchaseOrder()
        } else {
          form.value = {
            ...emptyForm(),
            quantity: shortage.value,
            expected_delivery_date: defaultDeliveryDate()
          }
        }
      },
      { immediate: true }
    )

    const close = () => {
      emit('close')
    }

    const submit = async () => {
      if (!canSubmit.value) return
      try {
        submitting.value = true
        error.value = null
        const created = await api.createPurchaseOrder({
          backlog_item_id: props.backlogItem.id,
          supplier_name: form.value.supplier_name.trim(),
          quantity: Number(form.value.quantity),
          unit_cost: Number(form.value.unit_cost),
          expected_delivery_date: form.value.expected_delivery_date,
          notes: form.value.notes.trim() || null
        })
        emit('po-created', created)
      } catch (err) {
        error.value = err.response?.data?.detail || t('purchaseOrder.createError')
        console.error('Failed to create purchase order:', err)
      } finally {
        submitting.value = false
      }
    }

    return {
      t,
      currentCurrency,
      translateProductName,
      formatCurrency,
      loading,
      submitting,
      error,
      purchaseOrder,
      form,
      shortage,
      estimatedTotal,
      canSubmit,
      close,
      submit
    }
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  width: 90%;
  max-width: 700px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 2rem;
  border-bottom: 2px solid #e2e8f0;
}

.modal-title {
  font-size: 1.5rem;
  font-weight: 600;
  color: #0f172a;
  margin: 0;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  padding: 2rem;
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  padding: 1.5rem 2rem;
  border-top: 2px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
}

.btn-secondary {
  padding: 0.75rem 1.5rem;
  background: #f1f5f9;
  color: #475569;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-secondary:hover {
  background: #e2e8f0;
}

.btn-primary {
  padding: 0.75rem 1.5rem;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.item-summary {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
  background: #f8fafc;
  border-radius: 12px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem;
}

.summary-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.summary-label {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.025em;
  color: #64748b;
}

.summary-value {
  font-size: 0.95rem;
  font-weight: 600;
  color: #0f172a;
}

.summary-value.danger {
  color: #dc2626;
}

.po-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-row {
  display: flex;
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  flex: 1;
}

label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #475569;
}

.po-input {
  padding: 0.75rem;
  border: 2px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.95rem;
  font-family: inherit;
  transition: border-color 0.2s ease;
}

.po-input:focus {
  outline: none;
  border-color: #2563eb;
}

.form-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 1rem;
  color: #475569;
}

.form-total strong {
  font-size: 1.25rem;
  color: #0f172a;
}

.po-details {
  display: flex;
  flex-direction: column;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.875rem 0;
  border-bottom: 1px solid #e2e8f0;
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
}

.detail-value {
  font-size: 0.95rem;
  color: #0f172a;
  text-align: right;
}

.badge {
  display: inline-block;
  padding: 0.25rem 0.625rem;
  border-radius: 4px;
  background: #dbeafe;
  color: #1e40af;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.state-message {
  padding: 1.5rem;
  text-align: center;
  color: #64748b;
}

.state-message.error {
  color: #b91c1c;
  background: #fef2f2;
  border-radius: 8px;
  padding: 1rem;
  text-align: left;
  font-size: 0.9rem;
}

/* Modal transitions */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: transform 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.9);
}
</style>
